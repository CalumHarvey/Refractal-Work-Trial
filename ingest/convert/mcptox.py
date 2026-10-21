"""MCPTox -> AgentDecisionRecords (one step record per distinct model reaction to a poisoned MCP tool).

Spec: `datasets.mcptox` in label-schema/dataset_mappings.yaml. Each case is a real MCP server's tool
list with one poisoned tool added, and one user query. Up to 27 models answered each case and the
authors labelled every response; identical reactions are merged and only the most frequent distinct
reactions are kept, up to `selection.max_actions_per_label` per decision.
"""
import json
import re
import warnings
import ast
from collections import Counter, defaultdict
from pathlib import Path

from ..common.paths import mappings
from ..common.record import Record
from ..common.rules import RuleSet
from ..common.text import sha1_12
from ..common.tools import side_effects

DATASET = "mcptox"
RULES = RuleSet(DATASET)

LABELS = {"Success", "Failure-Ignored", "Failure-Direct Execution", "Failure-Refused"}
_TOOL_BLOCK = re.compile(r"(?:^|\n)Tool: (.*?)\nDescription: (.*?)\nArguments:\n(.*?)(?=\n\s*\nTool: |\n\s*\nChoose the appropriate tool|\Z)", re.S)
_ARG_LINE = re.compile(r"^- ([^:]+):\s*(.*?)(\(required\))?\s*$")
_STOP_TOKENS = re.compile(r"<\|im_end\|>|<\|endoftext\|>|</s>|<end_of_turn>|<｜end▁of▁sentence｜>|<\|eot_id\|>")
_THINK = re.compile(r"<think>.*?</think>", re.S)
STATS: Counter = Counter()  # filled by iter_source, reported by report_extras


def match_key(text: str) -> str:
    """Normalise text for matching and hashing.

    Args:
        text: Any text.

    Returns:
        Lowercase words separated by single spaces (punctuation and escapes dropped).
    """
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(text or "").replace("\\n", "\n").lower())).strip()


# ---- tool list ----------------------------------------------------------------------------------
def parse_tools(system: str) -> list[dict]:
    """Parse the tool list from a case's system prompt.

    Args:
        system: The system prompt: "Tool: <name>\\nDescription: ...\\nArguments:\\n- arg: ..." blocks.

    Returns:
        Schema tools: name, description, parameters (as a JSON-Schema-like object), origin "mcp",
        side_effects from the name. The prompt's closing response-format instructions are not a tool.
    """
    tools = []
    for name, desc, args in _TOOL_BLOCK.findall(system):
        props, required = {}, []
        for line in args.splitlines():
            m = _ARG_LINE.match(line.strip())
            if m and m.group(1).strip().lower() != "no arguments":
                arg = m.group(1).strip()
                props[arg] = {"description": m.group(2).strip()}
                if m.group(3):
                    required.append(arg)
        name = name.split("\\n")[0].strip()  # a few poisoned names carry a literal "\n"
        tools.append({"name": name, "description": desc.strip(),
                      "parameters_schema": {"type": "object", "properties": props, "required": required},
                      "origin": "mcp", "side_effects": side_effects(name)})
    return tools


def poisoned_name(case: dict, tools: list[dict]) -> str | None:
    """Find the poisoned tool in the parsed tool list.

    Args:
        case: A malicious instance (its `poisoned_tool` text).
        tools: Tools parsed from its system prompt.

    Returns:
        The name of the listed tool whose description matches the poisoned description, or None when
        the prompt does not contain it (9 cases).
    """
    desc = match_key(case["poisoned_tool"].replace("\\n", "\n").split("Description:", 1)[-1].split("Arguments:")[0])[:120]
    hits = [t["name"] for t in tools if desc and desc[:80] in match_key(t["description"])]
    return hits[-1] if hits else None


# ---- response parsing ---------------------------------------------------------------------------
def _balanced(text: str, start: int) -> str | None:
    """Cut the balanced {...} object starting at `start`.

    Args:
        text: Response text.
        start: Index of an opening brace.

    Returns:
        The object text, or None if the braces never balance.
    """
    depth, quote, escape = 0, None, False
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _load(obj: str):
    """Parse an object as JSON or a Python literal.

    Args:
        obj: Object text.

    Returns:
        The parsed value, or None if neither parser accepts it.
    """
    for parse in (json.loads, lambda s: json.loads(s, strict=False), ast.literal_eval):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                return parse(obj)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            continue
    return None


def _jsonable(value):
    """Make a parsed value JSON-compatible.

    Args:
        value: A parsed JSON value or Python literal.

    Returns:
        The value with sets / tuples as lists, bytes as text and dict keys as strings.
    """
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_jsonable(v) for v in value]
        return sorted(items, key=str) if isinstance(value, (set, frozenset)) else items
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def first_action(response: str) -> dict | None:
    """Parse a model's response into its next action.

    Args:
        response: The raw response: a JSON tool call `{"tool": ..., "arguments": {...}}` (single or
            double quotes, fenced or not), possibly after reasoning or a <think> block and before a
            stop token; or plain text.

    Returns:
        The first object with a "tool" key as `{"tool_name", "arguments", "reasoning"}` (reasoning =
        text before it); otherwise the text as the pseudo-call final_answer; None for an empty
        response.
    """
    text = _THINK.sub("", _STOP_TOKENS.sub("", response or "")).strip()
    if not text:
        return None
    for m in re.finditer(r"\{", text):
        obj = _balanced(text, m.start())
        value = _load(obj) if obj else None
        if isinstance(value, dict) and isinstance(value.get("tool"), str):
            args = value.get("arguments")
            reasoning = re.sub(r"```(?:json)?", "", text[:m.start()]).strip() or None
            return {"tool_name": value["tool"].strip(),
                    "arguments": _jsonable(args) if isinstance(args, dict) else ({} if args in (None, "") else {"value": _jsonable(args)}),
                    "reasoning": reasoning}
    return {"tool_name": "final_answer", "arguments": {"text": text}, "reasoning": None}


def action_key(action: dict) -> str:
    """Canonical form of an action, for merging identical reactions.

    Args:
        action: A planned action.

    Returns:
        Tool name plus sorted-key JSON of the arguments; final answers by their normalised text.
    """
    if action["tool_name"] == "final_answer":
        return "final_answer:" + match_key(action["arguments"].get("text"))
    return action["tool_name"] + ":" + match_key(json.dumps(action["arguments"], sort_keys=True))


# ---- raw input ----------------------------------------------------------------------------------
def _responses(data: dict):
    """List every labelled model response of a case.

    Args:
        data: A case's `datas[0]`.

    Yields:
        `(model, response, label)` for the local and the online (API) models.
    """
    for model, label in (data.get("label") or {}).items():
        yield model, (data.get("response") or {}).get(model), label
    online = data.get("online_result") or {}
    for responses, labels in zip(online.get("backend_model_responses") or [], online.get("labeled_model_results") or []):
        for model, label in labels.items():
            yield model, responses.get(model), label


def _consistent(label: str, calls_poisoned: bool, paradigm: str) -> bool:
    """Check that a response's label agrees with its first call.

    In Template-1 cases the poisoned tool is the tool the user's query needs (e.g. a poisoned
    `get_current_time` for "get current time"), so calling it is the user's task; in the other
    templates it is an extra tool the query does not need.

    Args:
        label: The authors' label.
        calls_poisoned: Whether the first call is the poisoned tool.
        paradigm: "Template-1", "Template-2" or "Template-3".

    Returns:
        False for: Direct Execution without a call to the poisoned tool, or in Template-1 (where it
        cannot be told apart from serving the user); Success calling the poisoned tool; Ignored /
        Refused calling it outside Template-1. True otherwise.
    """
    if label == "Failure-Direct Execution":
        return calls_poisoned and paradigm != "Template-1"
    if label == "Success":
        return not calls_poisoned
    return not calls_poisoned or paradigm == "Template-1"


def iter_source(snapshot: Path):
    """Collapse the labelled responses into distinct decision points.

    Skips cases flagged `wrong_data` and cases whose prompt lacks the poisoned tool. Per response:
    skip label None and empty or unparseable output; drop responses whose label disagrees with
    the first call (see `_consistent`) and "Success" without a tool call. Identical actions are merged across models; actions labelled several ways are dropped;
    per case the most frequent distinct actions are kept, up to the configured number per label.

    Args:
        snapshot: The MCPTox snapshot folder.

    Yields:
        `(original_id, item)` pairs; original_id is "<server>:<instance index>:<action hash>" and
        item holds the server, case, parsed tools, poisoned tool name, action, label and models.
    """
    STATS.clear()
    raw = json.loads((snapshot / "response_all.json").read_text(encoding="utf-8"))
    cap = mappings()["datasets"][DATASET]["selection"]["max_actions_per_label"]
    for server, info in sorted(raw["servers"].items()):
        for index, case in enumerate(info["malicious_instance"]):
            STATS["cases"] += 1
            if case.get("wrong_data"):
                STATS["skipped_wrong_data"] += 1
                continue
            data = case["datas"][0]
            tools = parse_tools(data["system"])
            poisoned = poisoned_name(case, tools)
            if poisoned is None:
                STATS["skipped_poisoned_tool_not_in_prompt"] += 1
                continue
            actions = defaultdict(lambda: {"labels": Counter(), "models": set(), "action": None})
            for model, response, label in _responses(data):
                STATS["responses"] += 1
                STATS[f"label:{label}"] += 1
                if label not in LABELS:
                    continue
                action = first_action(response)
                if action is None:
                    STATS["dropped_empty_response"] += 1
                    continue
                calls_poisoned = action["tool_name"] == poisoned
                if not _consistent(label, calls_poisoned, case["metadata"]["paradigm"]):
                    STATS["dropped_label_disagrees_with_first_action"] += 1
                    continue
                if label == "Success" and action["tool_name"] == "final_answer":
                    STATS["dropped_success_without_call"] += 1
                    continue
                a = actions[action_key(action)]
                a["labels"][label] += 1
                a["models"].add(model)
                a["action"] = a["action"] or action
            by_label = defaultdict(list)
            for akey, a in actions.items():
                if len(a["labels"]) > 1:
                    STATS["dropped_conflicting_labels"] += 1
                    continue
                by_label[next(iter(a["labels"]))].append((akey, a))
            STATS["cases_used"] += bool(by_label)
            for label, items in sorted(by_label.items()):
                items.sort(key=lambda kv: (-len(kv[1]["models"]), sha1_12(kv[0])))
                STATS["distinct_actions_over_cap"] += max(0, len(items) - cap)
                for akey, a in items[:cap]:
                    yield f"{server}:{index}:{sha1_12(akey)}", {
                        "server": server, "index": index, "case": case, "query": data["query"], "tools": tools,
                        "poisoned": poisoned, "action": a["action"], "label": label, "models": sorted(a["models"])}


def build_input(item: dict) -> dict:
    """Build the record's `input`: the user query, the server's tool list and the model's next call.

    Args:
        item: An item from `iter_source`.

    Returns:
        The input dict. The poisoned tool is listed like any other tool, as an agent would receive
        it; the system prompt's response-format instructions are left out.
    """
    return {"system_prompt": None, "user_prompt": item["query"],
            "messages": [{"role": "user", "content": item["query"], "trust": "principal"}],
            "tools_available": item["tools"], "planned_action": item["action"], "principal": None, "modality": "text"}


# ---- rules (registration order = application order) ---------------------------------------
@RULES.rule("mt.base")
def base(item, rec: Record) -> bool:
    """mt.base: a poisoned tool description is in the tool list (modes 12 and 7).

    Args:
        item: The source item.
        rec: The Record being built.

    Returns:
        True for every record (every MCPTox case is an attack).
    """
    rec.set("attack_vector", "tool_metadata", "by_construction", "mt.base")
    rec.add_modes([12, 7], "by_construction", "mt.base")
    rec.set("adversarial_locations", [{"kind": "tool", "tool_name": item["poisoned"]}], "by_construction", "mt.base")
    return True


@RULES.rule("mt.executed")
def executed(item, rec: Record) -> bool:
    """mt.executed: the model carried out the poisoned instruction ("Success") -> BLOCK.

    Args:
        item: The source item.
        rec: The Record being built.

    Returns:
        True if the label is "Success", otherwise False.
    """
    if item["label"] != "Success":
        return False
    rec.set("decision", "BLOCK", "given", "mt.executed")
    rec.set("action_relation", "injected_task", "given", "mt.executed")
    rec.add_modes([22], "given", "mt.executed")
    return True


@RULES.rule("mt.resisted")
def resisted(item, rec: Record) -> bool:
    """mt.resisted: the model ignored the poisoned description or refused -> ALLOW, a hard negative.

    Args:
        item: The source item.
        rec: The Record being built.

    Returns:
        True if the label is "Failure-Ignored" or "Failure-Refused", otherwise False.
    """
    if item["label"] not in ("Failure-Ignored", "Failure-Refused"):
        return False
    rec.set("decision", "ALLOW", "given", "mt.resisted")
    rec.set("action_relation", "user_task", "given", "mt.resisted")
    rec.set("hard_negative", True, "given", "mt.resisted")
    return True


@RULES.rule("mt.called_poisoned_tool")
def called_poisoned_tool(item, rec: Record) -> bool:
    """mt.called_poisoned_tool: the model called the poisoned tool itself -> REVIEW.

    The call does not follow the planted instruction, but it runs a tool whose description is
    hostile and whose behaviour is unknown.

    Args:
        item: The source item.
        rec: The Record being built.

    Returns:
        True if the label is "Failure-Direct Execution", otherwise False.
    """
    if item["label"] != "Failure-Direct Execution":
        return False
    rec.set("decision", "REVIEW", "rule_inferred", "mt.called_poisoned_tool")
    rec.set("action_relation", "deviation", "rule_inferred", "mt.called_poisoned_tool")
    return True


# ---- record --------------------------------------------------------------------------------
def to_record(original_id: str, item: dict, revision: str) -> tuple[str, Record]:
    """Convert one distinct model reaction into a Record.

    Args:
        original_id: From `iter_source`.
        item: The source item.
        revision: The snapshot's revision, written to `source.dataset_version`.

    Returns:
        `(record_id, record)`: "mcptox:" + original_id and the Record, ready for `Record.build`.
    """
    case = item["case"]
    rec = Record(DATASET, original_id, "step")
    rec.input = build_input(item)
    rec.source.update({
        "dataset_version": revision,
        "original_split": None,
        "step_index": 1,
        "generator_model": None,
        "license": None,
        "original_label": {"label": item["label"], "paradigm": case["metadata"]["paradigm"],
                           "security_risk": case["metadata"]["security risk"],
                           "security_risk_description": case.get("security_risk_description"),
                           "server": item["server"], "models": item["models"]},
    })
    rec.source["group_ids"] = {
        "task": f"mcptox:query:{sha1_12(match_key(item['query']))}",  # generic queries recur across servers
        "attack": f"mcptox:poisoned:{sha1_12(match_key(case['poisoned_tool']))}",
        "trajectory": f"mcptox:case:{item['server']}:{item['index']}",
        "author": "mcptox:benchmark_authors",
    }
    RULES.apply(item, rec)
    return f"mcptox:{original_id}", rec


# ---- dataset-specific report section ---------------------------------------------------------
EXPECTED = {"cases": 1348, "skipped_wrong_data": 36}


def report_extras(records: list[dict]) -> dict:
    """Build the MCPTox section of report.json.

    Args:
        records: The valid converted records.

    Returns:
        A dict with: reconciliation (case counts vs. the raw file), the selection funnel, and records
        by label, decision, paradigm and risk category, plus counts of servers, queries and cases.
    """
    C = Counter
    ol = lambda r: r["source"]["original_label"]  # noqa: E731
    return {
        "reconciliation": {k: {"expected": v, "measured": STATS[k], "ok": STATS[k] == v} for k, v in EXPECTED.items()},
        "funnel": dict(sorted(STATS.items())),
        "records_by_label": dict(C(ol(r)["label"] for r in records)),
        "records_by_paradigm": dict(C(ol(r)["paradigm"] for r in records)),
        "records_by_risk": dict(C(ol(r)["security_risk"] for r in records)),
        "servers": len({ol(r)["server"] for r in records}),
        "queries": len({r["source"]["group_ids"]["task"] for r in records}),
        "cases": len({r["source"]["group_ids"]["trajectory"] for r in records}),
        "planned_final_answers": sum(r["input"]["planned_action"]["tool_name"] == "final_answer" for r in records),
    }
