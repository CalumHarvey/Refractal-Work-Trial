"""R-Judge -> AgentDecisionRecords (one trajectory record per run).

Spec: `datasets.r_judge` in label-schema/dataset_mappings.yaml.
"""
import ast
import json
import re
from collections import Counter
from pathlib import Path

from ..common.record import Record
from ..common.rules import RuleSet
from ..common.text import unquote

DATASET = "r_judge"
RULES = RuleSet(DATASET)

# Agent action forms seen in the data (see the mappings comment for counts).
_ACTION_INPUT = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*\n\s*Action Input:\s*(.*)$", re.S)
_INLINE_CALL = re.compile(r"^\s*([A-Z][A-Za-z0-9_]*)\s*:?\s*(\{.*\}|\[.*\])\s*$", re.S)
_FINAL_ANSWER = re.compile(r"^\s*Final Answer\s*:?\s*", re.S)


# ---- raw input ---------------------------------------------------------------------------
def iter_source(snapshot: Path):
    """Read every run from the raw snapshot, in a stable order.

    Files that cannot be read (data/Program/security.json is blocked on this machine) are
    skipped; the raw manifest records the gap.

    Args:
        snapshot: The R-Judge pinned-commit folder.

    Yields:
        `(original_id, run)` pairs. original_id is "<domain>/<file stem>:<id>"; the run dict gets
        two extra keys, "_domain" and "_file" (the stem), used for ids and original_label.
    """
    for path in sorted((snapshot / "data").rglob("*.json")):
        try:
            runs = json.loads(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        for run in runs:
            run = dict(run, _domain=path.parent.name, _file=path.stem)
            yield f"{path.parent.name}/{path.stem}:{run['id']}", run


def parse_args(text: str) -> dict:
    """Parse tool-call arguments written as JSON or as a Python literal.

    Args:
        text: The argument text, e.g. '{"guest_ids": ["guest_amy01"]}' or "{'email_id': 'e1'}".

    Returns:
        The arguments as a dict. A non-dict value is wrapped as {"value": ...}; text that parses as
        neither JSON nor a Python literal (e.g. arithmetic, or several calls in one action) is kept
        as {"raw": text}.
    """
    text = text.strip()
    parsers = (
        json.loads,
        lambda s: json.loads(s, strict=False),           # raw line breaks inside JSON strings
        ast.literal_eval,
        lambda s: ast.literal_eval(s.replace("\n", "\\n")),  # raw line breaks inside Python strings
    )
    for parse in parsers:
        try:
            value = parse(text)
            break
        except (ValueError, SyntaxError):
            continue
    else:
        return {"raw": text}
    return value if isinstance(value, dict) else {"value": value}


def parse_action(action: str | None) -> tuple[dict | None, str]:
    """Split an agent action into a tool call or message text.

    Args:
        action: The raw action string (may be None).

    Returns:
        `(tool_call, text)`. For a tool call, tool_call is `{"tool_name", "arguments"}` and text is
        "". Otherwise tool_call is None and text is the reply ("Final Answer:" prefix removed).
    """
    action = action or ""
    for pattern in (_ACTION_INPUT, _INLINE_CALL):
        m = pattern.match(action)
        if m:
            return {"tool_name": m.group(1), "arguments": parse_args(m.group(2))}, ""
    return None, _FINAL_ANSWER.sub("", action, count=1)


def build_input(run: dict) -> tuple[dict, list[int]]:
    """Build the record's `input` from a raw run.

    Segments are flattened in order. User turns are principal messages; agent turns become an
    assistant message with a tool call (thought as reasoning) or with the reply text; environment
    turns are tool outputs, unquoted, with null content as "". No tools_available: the data has no
    tool list, and one built from the calls would leak the label.

    Args:
        run: A raw R-Judge run.

    Returns:
        `(input, tool_message_indexes)`: the input dict and the indexes of the tool-output messages,
        in order.

    Raises:
        ValueError: If a turn has an unknown role.
    """
    messages, tool_indexes, last_tool = [], [], None
    for segment in run["contents"]:
        for turn in segment:
            role = turn["role"]
            if role == "user":
                messages.append({"role": "user", "content": turn.get("content") or "", "trust": "principal"})
            elif role == "agent":
                thought = turn.get("thought") or None
                call, text = parse_action(turn.get("action"))
                if call:
                    call["reasoning"] = thought
                    last_tool = call["tool_name"]
                    messages.append({"role": "assistant", "content": "", "trust": "agent_generated",
                                     "tool_call": call})
                else:
                    content = text if not thought else (f"{thought}\n\n{text}" if text else thought)
                    messages.append({"role": "assistant", "content": content, "trust": "agent_generated"})
            elif role == "environment":
                content = turn.get("content")
                content = "" if content is None else unquote(content if isinstance(content, str) else json.dumps(content))
                tool_indexes.append(len(messages))
                messages.append({"role": "tool", "content": content, "trust": "tool_output", "tool_name": last_tool})
            else:
                raise ValueError(f"unknown role {role!r}")
    first_user = next((m["content"] for m in messages if m["role"] == "user"), None)
    return ({"system_prompt": run.get("profile") or None, "user_prompt": first_user, "messages": messages,
             "planned_action": None, "principal": None, "modality": "text"}, tool_indexes)


# ---- rules (registration order = application order) ---------------------------------------
@RULES.rule("rj.safe")
def safe(run, rec: Record) -> bool:
    """rj.safe: a safe run (label 0) becomes ALLOW.

    Args:
        run: The raw run.
        rec: The Record being built.

    Returns:
        True if the run is safe, otherwise False.
    """
    if run["label"] != 0:
        return False
    rec.set("decision", "ALLOW", "given", "rj.safe")
    return True


@RULES.rule("rj.unsafe")
def unsafe(run, rec: Record) -> bool:
    """rj.unsafe: an unsafe run (label 1) becomes BLOCK.

    Args:
        run: The raw run.
        rec: The Record being built.

    Returns:
        True if the run is unsafe, otherwise False.
    """
    if run["label"] != 1:
        return False
    rec.set("decision", "BLOCK", "given", "rj.unsafe")
    return True


@RULES.rule("rj.injection")
def injection(run, rec: Record) -> bool:
    """rj.injection: an injection run has its attack in a tool output (mode 16).

    Args:
        run: The raw run.
        rec: The Record being built.

    Returns:
        True if attack_type is "injection", otherwise False.
    """
    if run["attack_type"] != "injection":
        return False
    rec.set("attack_vector", "tool_output", "given", "rj.injection")
    rec.add_modes([16], "given", "rj.injection")
    return True


@RULES.rule("rj.injection_block")
def injection_block(run, rec: Record) -> bool:
    """rj.injection_block: an unsafe injection run also shows excessive agency (mode 22).

    Args:
        run: The raw run.
        rec: The Record being built.

    Returns:
        True if the run is an unsafe injection run, otherwise False.
    """
    if run["attack_type"] != "injection" or run["label"] != 1:
        return False
    rec.add_modes([22], "rule_inferred", "rj.injection_block")
    return True


@RULES.rule("rj.injection_safe")
def injection_safe(run, rec: Record) -> bool:
    """rj.injection_safe: a safe injection run is a hard negative.

    Args:
        run: The raw run.
        rec: The Record being built.

    Returns:
        True if the run is a safe injection run, otherwise False.
    """
    if run["attack_type"] != "injection" or run["label"] != 0:
        return False
    rec.set("hard_negative", True, "given", "rj.injection_safe")
    return True


@RULES.rule("rj.injection_location")
def injection_location(run, rec: Record) -> bool:
    """rj.injection_location: in an injection run, the first tool output holds the attack.

    Uses the tool-message indexes `build_input` stored in `rec.scratch["tool_messages"]`.

    Args:
        run: The raw run.
        rec: The Record being built.

    Returns:
        True if the run is an injection run with at least one tool output, otherwise False.
    """
    tools = rec.scratch.get("tool_messages", [])
    if run["attack_type"] != "injection" or not tools:
        return False
    rec.set("adversarial_locations", [{"kind": "message", "message_index": tools[0]}],
            "by_construction", "rj.injection_location")
    return True


@RULES.rule("rj.unintended_safe")
def unintended_safe(run, rec: Record) -> bool:
    """rj.unintended_safe: a safe run with no attacker has no attack and no failure mode.

    Args:
        run: The raw run.
        rec: The Record being built.

    Returns:
        True if the run is a safe "unintended" run, otherwise False.
    """
    if run["attack_type"] != "unintended" or run["label"] != 0:
        return False
    rec.set("attack_vector", "none", "given", "rj.unintended_safe")
    rec.set_no_modes("given", "rj.unintended_safe")
    return True


@RULES.rule("rj.unintended_unsafe")
def unintended_unsafe(run, rec: Record) -> bool:
    """rj.unintended_unsafe: an unsafe run with no attacker; its cause is left for backfill.

    Args:
        run: The raw run.
        rec: The Record being built.

    Returns:
        True if the run is an unsafe "unintended" run, otherwise False.
    """
    if run["attack_type"] != "unintended" or run["label"] != 1:
        return False
    rec.set("attack_vector", "none", "given", "rj.unintended_unsafe")
    rec.flag_backfill("failure_modes")
    return True


# ---- record --------------------------------------------------------------------------------
def to_record(original_id: str, run: dict, revision: str) -> tuple[str, Record]:
    """Convert one R-Judge run into a Record.

    Args:
        original_id: "<domain>/<file stem>:<id>", from `iter_source`.
        run: The raw run, with the "_domain" and "_file" keys `iter_source` adds.
        revision: The raw snapshot's commit, written to `source.dataset_version`.

    Returns:
        `(record_id, record)`: "r_judge:<original_id>" and the Record, ready for `Record.build`.
    """
    rec = Record(DATASET, original_id, "trajectory")
    rec.source.update({
        "dataset_version": revision,
        "original_split": None,
        "step_index": None,
        "generator_model": None,
        "license": None,
        "original_label": {"label": run["label"], "attack_type": run["attack_type"], "scenario": run.get("scenario"),
                           "risk_description": run.get("risk_description"),
                           "domain": run["_domain"], "file": run["_file"]},
    })
    key = f"r_judge:{original_id}"
    rec.source["group_ids"] = {"task": key, "attack": f"r_judge:{run['attack_type']}",
                               "trajectory": key, "author": "r_judge:benchmark_authors"}
    rec.input, rec.scratch["tool_messages"] = build_input(run)
    RULES.apply(run, rec)
    return key, rec


# ---- dataset-specific report section ---------------------------------------------------------
# 569 upstream minus ~5 in data/Program/security.json, which is unreadable here.
EXPECTED = {"records": 564, "unsafe": 298, "safe": 266, "injection": 414, "unintended": 150,
            "hard_negatives": 214, "backfill_failure_modes": 98, "injection_locations": 414}


def report_extras(records: list[dict]) -> dict:
    """Build the R-Judge section of report.json.

    Args:
        records: The valid converted records.

    Returns:
        A dict with: reconciliation (each count vs. its expected raw value), how tool calls were
        parsed, how many arguments fell back to raw text, and message-role counts.
    """
    C = Counter
    lab = lambda r, k: r["labels"][k]  # noqa: E731
    calls = [m["tool_call"] for r in records for m in r["input"]["messages"] if m.get("tool_call")]
    checks = {
        "records": len(records),
        "unsafe": sum(lab(r, "decision") == "BLOCK" for r in records),
        "safe": sum(lab(r, "decision") == "ALLOW" for r in records),
        "injection": sum(r["source"]["original_label"]["attack_type"] == "injection" for r in records),
        "unintended": sum(r["source"]["original_label"]["attack_type"] == "unintended" for r in records),
        "hard_negatives": sum(lab(r, "hard_negative") is True for r in records),
        "backfill_failure_modes": sum("failure_modes" in r["needs_backfill"] for r in records),
        "injection_locations": sum(bool(lab(r, "adversarial_locations")) for r in records),
    }
    return {
        "reconciliation": {k: {"expected": EXPECTED[k], "got": v, "ok": EXPECTED[k] == v} for k, v in checks.items()},
        "tool_calls": len(calls),
        "tool_call_args_unparsed": sum("raw" in c["arguments"] and len(c["arguments"]) == 1 for c in calls),
        "message_roles": dict(C(m["role"] for r in records for m in r["input"]["messages"])),
        "assistant_text_turns": sum(1 for r in records for m in r["input"]["messages"]
                                    if m["role"] == "assistant" and not m.get("tool_call")),
        "attack_wording_in_first_tool_output": sum(
            1 for r in records if lab(r, "adversarial_locations")
            and "ignore all previous" in r["input"]["messages"][lab(r, "adversarial_locations")[0]["message_index"]]["content"].lower()),
        "attack_wording_in_later_tool_outputs": sum(
            1 for r in records if lab(r, "adversarial_locations")
            and any("ignore all previous" in m["content"].lower()
                    for i, m in enumerate(r["input"]["messages"])
                    if m["role"] == "tool" and i != lab(r, "adversarial_locations")[0]["message_index"])),
    }
