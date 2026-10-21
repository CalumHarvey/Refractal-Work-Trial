"""ToolACE -> AgentDecisionRecords (benign function-calling steps).

Spec: `datasets.toolace` in label-schema/dataset_mappings.yaml. Each dialog has a system prompt
holding a JSON tool list and turns `user` / `assistant` / `tool`. Assistant tool calls are written
as `[Tool Name(arg="v", n=1), Other(x=2)]`. Every assistant turn that makes tool calls becomes an
ALLOW step (no attacker is involved); text replies are not used.
"""
import ast
import hashlib
import json
import re
import warnings
from collections import Counter
from pathlib import Path

from ..common.paths import mappings
from ..common.record import Record
from ..common.rules import RuleSet
from ..common.text import normalise, sha1_12
from ..common.tools import side_effects

DATASET = "toolace"
RULES = RuleSet(DATASET)
STATS: Counter = Counter()
_TOOLS_MARKER = "Here is a list of functions in JSON format that you can invoke:"


def parse_tools(system: str) -> list[dict]:
    """Read the JSON tool list from a ToolACE system prompt.

    Args:
        system: The system prompt.

    Returns:
        Schema tools; empty if the list cannot be found or parsed.
    """
    start = system.find("[", system.find(_TOOLS_MARKER))
    if start < 0:
        return []
    try:
        tools, _ = json.JSONDecoder().raw_decode(system[start:])
    except json.JSONDecodeError:
        return []
    return [{"name": t["name"], "description": t.get("description"),
             "parameters_schema": t.get("parameters") if isinstance(t.get("parameters"), dict) else None,
             "origin": "unknown", "side_effects": side_effects(t["name"])} for t in tools if isinstance(t, dict) and "name" in t]


def _split_calls(body: str) -> list[str]:
    """Split the inside of `[...]` into top-level call strings.

    Args:
        body: Text between the outer brackets.

    Returns:
        One string per call, split at commas outside parentheses and quotes.
    """
    parts, depth, quote, cur = [], 0, None, ""
    for ch in body:
        if quote:
            quote = None if ch == quote and not cur.endswith("\\") else quote
        elif ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
            continue
        cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def parse_calls(text: str) -> list[dict] | None:
    """Parse an assistant turn written in ToolACE's call syntax.

    Args:
        text: The assistant turn.

    Returns:
        `[{"tool_name", "arguments", "reasoning": None}]`, or None if the turn is not a call list or
        an argument cannot be read as a Python literal.
    """
    text = text.strip()
    if not (text.startswith("[") and text.endswith("]")):
        return None
    calls = []
    for part in _split_calls(text[1:-1]):
        m = re.match(r"^\s*([^()]+?)\s*\((.*)\)\s*$", part, re.S)
        if not m:
            return None
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                node = ast.parse(f"_f({m.group(2)})", mode="eval").body
            if not isinstance(node, ast.Call) or node.args or any(kw.arg is None for kw in node.keywords):
                return None  # only keyword arguments are valid in ToolACE's syntax
            args = {kw.arg: ast.literal_eval(kw.value) for kw in node.keywords}
        except (SyntaxError, ValueError):
            return None
        calls.append({"tool_name": m.group(1).strip(), "arguments": json.loads(json.dumps(args, default=str)), "reasoning": None})
    return calls or None


def iter_source(snapshot: Path):
    """Select benign tool-call steps.

    Per dialog, every assistant turn that is a call list is a decision point; the first call of the
    turn is the planned action and the context is everything before the turn. At most
    `max_records` records are kept, in a stable pseudo-random order over dialogs.

    Args:
        snapshot: The ToolACE snapshot folder.

    Yields:
        `(original_id, item)` pairs; original_id is "<dialog index>:<turn index>".
    """
    STATS.clear()
    cap = mappings()["datasets"][DATASET]["selection"]["max_records"]
    dialogs = json.loads((snapshot / "data.json").read_text(encoding="utf-8"))
    STATS["dialogs"] = len(dialogs)
    order = sorted(range(len(dialogs)), key=lambda i: hashlib.sha256(str(i).encode()).hexdigest())
    kept = 0
    for i in order:
        d = dialogs[i]
        tools = parse_tools(d.get("system", ""))
        if not tools:
            STATS["dialogs_without_tool_list"] += 1
            continue
        names = {t["name"] for t in tools}
        messages = []
        for j, turn in enumerate(d["conversations"]):
            role, value = turn["from"], turn["value"]
            if role == "user":
                messages.append({"role": "user", "content": value, "trust": "principal"})
            elif role == "tool":
                messages.append({"role": "tool", "content": value, "trust": "tool_output", "tool_name": None})
            elif role == "assistant":
                calls = parse_calls(value)
                if calls is None:
                    if value.strip().startswith("["):
                        STATS["unparsed_call_turns"] += 1
                    messages.append({"role": "assistant", "content": value, "trust": "agent_generated"})
                    continue
                if calls[0]["tool_name"] in names and kept < cap:
                    kept += 1
                    yield f"{i}:{j}", {"index": i, "messages": list(messages), "action": calls[0], "tools": tools}
                elif calls[0]["tool_name"] not in names:
                    STATS["calls_to_unlisted_tool"] += 1
                for c in calls:
                    messages.append({"role": "assistant", "content": "", "trust": "agent_generated", "tool_call": c})


@RULES.rule("ta.benign")
def benign(item, rec: Record) -> bool:
    """ta.benign: a function call serving the user's request, no attacker involved -> ALLOW.

    Args:
        item: The source item.
        rec: The Record being built.

    Returns:
        True for every record.
    """
    rec.set("decision", "ALLOW", "by_construction", "ta.benign")
    rec.set("attack_vector", "none", "by_construction", "ta.benign")
    rec.set_no_modes("by_construction", "ta.benign")
    rec.set("action_relation", "user_task", "by_construction", "ta.benign")
    rec.set("adversarial_locations", [], "by_construction", "ta.benign")
    rec.set("hard_negative", False, "by_construction", "ta.benign")
    return True


def to_record(original_id: str, item: dict, revision: str) -> tuple[str, Record]:
    """Convert one selected step into a Record.

    Args:
        original_id: From `iter_source`.
        item: The source item.
        revision: The snapshot revision.

    Returns:
        `(record_id, record)`: "toolace:" + original_id and the Record.
    """
    rec = Record(DATASET, original_id, "step")
    first_user = next((m["content"] for m in item["messages"] if m["role"] == "user"), "")
    rec.input = {"system_prompt": None, "user_prompt": first_user, "messages": item["messages"],
                 "tools_available": item["tools"], "planned_action": item["action"], "principal": None, "modality": "text"}
    planned = item["action"]["tool_name"]
    rec.source.update({"dataset_version": revision, "original_split": None, "step_index": len(item["messages"]),
                       "generator_model": None, "license": "Apache-2.0",
                       "original_label": {"planned_side_effects": next(t["side_effects"] for t in item["tools"] if t["name"] == planned)}})
    rec.source["group_ids"] = {"task": f"toolace:question:{sha1_12(normalise(first_user))}", "attack": None,
                               "trajectory": f"toolace:{item['index']}", "author": "toolace:benchmark_authors"}
    RULES.apply(item, rec)
    return f"toolace:{original_id}", rec


EXPECTED = {"dialogs": 11300}


def report_extras(records: list[dict]) -> dict:
    """Build the ToolACE section of report.json.

    Args:
        records: The valid converted records.

    Returns:
        Reconciliation of the dialog count, the funnel, and records by planned side effect.
    """
    return {"reconciliation": {k: {"expected": v, "measured": STATS[k], "ok": STATS[k] == v} for k, v in EXPECTED.items()},
            "funnel": dict(sorted(STATS.items())),
            "by_planned_side_effects": dict(Counter(r["source"]["original_label"]["planned_side_effects"] for r in records))}
