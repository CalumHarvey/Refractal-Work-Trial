"""When2Call -> AgentDecisionRecords (when to call a tool, ask, or decline).

Spec: `datasets.when2call` in label-schema/dataset_mappings.yaml. Each multiple-choice test item has
a question, a tool list and four candidate replies (direct answer, tool call, request for info,
cannot answer) with one marked correct. The correct reply becomes an ALLOW step (a tool call, or a
final answer that asks or declines). Where the correct reply is NOT a tool call, the candidate tool
call is unwarranted (missing information, or a tool that cannot do the job) and becomes a REVIEW
contrast in the same context. The "direct" answers are not used.
"""
import json
from collections import Counter
from pathlib import Path

from ..common.record import Record
from ..common.rules import RuleSet
from ..common.text import normalise, sha1_12
from ..common.tools import side_effects

DATASET = "when2call"
RULES = RuleSet(DATASET)
STATS: Counter = Counter()


def parse_tools(tools: list[str]) -> list[dict]:
    """Turn When2Call's JSON-string tool list into schema tools.

    Args:
        tools: Tool specs, each a JSON string with name, description and parameters.

    Returns:
        Schema tools; specs that are not valid JSON are skipped.
    """
    out = []
    for spec in tools:
        try:
            t = json.loads(spec)
        except json.JSONDecodeError:
            continue
        out.append({"name": t["name"], "description": t.get("description"),
                    "parameters_schema": t.get("parameters") if isinstance(t.get("parameters"), dict) else None,
                    "origin": "unknown", "side_effects": side_effects(t["name"])})
    return out


def _call(text: str) -> dict | None:
    """Parse a candidate tool call.

    Args:
        text: JSON with "name" and "arguments".

    Returns:
        A planned action, or None if the text is not a call.
    """
    try:
        c = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(c, dict) or "name" not in c:
        return None
    args = c.get("arguments")
    return {"tool_name": c["name"], "arguments": args if isinstance(args, dict) else {"value": args}, "reasoning": None}


def iter_source(snapshot: Path):
    """Turn each multiple-choice item into one ALLOW record, plus a REVIEW contrast where needed.

    Args:
        snapshot: The When2Call snapshot folder (only `test/when2call_test_mcq.jsonl` is used).

    Yields:
        `(original_id, item)` pairs; original_id is "<uuid>:<option>".
    """
    STATS.clear()
    for line in (snapshot / "test" / "when2call_test_mcq.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        q = json.loads(line)
        STATS["items"] += 1
        tools, correct, answers = parse_tools(q["tools"]), q["correct_answer"], q["answers"]
        base = {"uuid": q["uuid"], "question": q["question"], "tools": tools, "source": q["source"], "correct": correct}
        if correct == "tool_call":
            action = _call(answers.get("tool_call"))
            if action is None or action["tool_name"] not in {t["name"] for t in tools}:
                STATS["unusable_correct_call"] += 1
                continue
            yield f"{q['uuid']}:tool_call", dict(base, option="tool_call", action=action)
        else:
            yield f"{q['uuid']}:{correct}", dict(base, option=correct, action={
                "tool_name": "final_answer", "arguments": {"text": answers[correct]}, "reasoning": None})
            action = _call(answers.get("tool_call"))
            if action is not None:
                yield f"{q['uuid']}:tool_call", dict(base, option="tool_call", action=action)


# ---- rules (registration order = application order) ---------------------------------------
@RULES.rule("w2c.correct")
def correct(item, rec: Record) -> bool:
    """w2c.correct: the benchmark's correct reply (call, ask, or decline) -> ALLOW, no attack.

    Args:
        item: The source item.
        rec: The Record being built.

    Returns:
        True if the item is the correct option, otherwise False.
    """
    if item["option"] != item["correct"]:
        return False
    rec.set("decision", "ALLOW", "given", "w2c.correct")
    rec.set_no_modes("given", "w2c.correct")
    rec.set("action_relation", "user_task", "given", "w2c.correct")
    return True


@RULES.rule("w2c.unwarranted_call")
def unwarranted_call(item, rec: Record) -> bool:
    """w2c.unwarranted_call: a tool call where the right reply was to ask or decline -> REVIEW.

    Asking was right -> the call has to invent missing arguments (hallucination). Declining was
    right -> no listed tool can do what was asked (misinterpretation).

    Args:
        item: The source item.
        rec: The Record being built.

    Returns:
        True if the item is a tool call that is not the correct option, otherwise False.
    """
    if item["option"] != "tool_call" or item["correct"] == "tool_call":
        return False
    mode = "hallucination" if item["correct"] == "request_for_info" else "misinterpretation"
    rec.set("decision", "REVIEW", "rule_inferred", "w2c.unwarranted_call")
    rec.add_modes([mode], "rule_inferred", "w2c.unwarranted_call")
    rec.set("action_relation", "deviation", "rule_inferred", "w2c.unwarranted_call")
    return True


@RULES.rule("w2c.no_attack")
def no_attack(item, rec: Record) -> bool:
    """w2c.no_attack: no adversarial content anywhere in a When2Call item.

    Args:
        item: The source item.
        rec: The Record being built.

    Returns:
        True for every record.
    """
    rec.set("attack_vector", "none", "by_construction", "w2c.no_attack")
    rec.set("adversarial_locations", [], "by_construction", "w2c.no_attack")
    if item["option"] == item["correct"]:
        rec.set("hard_negative", False, "by_construction", "w2c.no_attack")
    return True


def to_record(original_id: str, item: dict, revision: str) -> tuple[str, Record]:
    """Convert one option into a Record.

    Args:
        original_id: From `iter_source`.
        item: The source item.
        revision: The snapshot revision.

    Returns:
        `(record_id, record)`: "when2call:" + original_id and the Record.
    """
    rec = Record(DATASET, original_id, "step")
    rec.input = {"system_prompt": None, "user_prompt": item["question"],
                 "messages": [{"role": "user", "content": item["question"], "trust": "principal"}],
                 "tools_available": item["tools"], "planned_action": item["action"], "principal": None, "modality": "text"}
    rec.source.update({"dataset_version": revision, "original_split": "test", "step_index": 1, "generator_model": None,
                       "license": "CC-BY-4.0",
                       "original_label": {"correct_answer": item["correct"], "option": item["option"], "source": item["source"],
                                          "toolset": sha1_12("|".join(sorted(t["name"] for t in item["tools"])))}})
    rec.source["group_ids"] = {"task": f"when2call:question:{sha1_12(normalise(item['question']))}", "attack": None,
                               "trajectory": f"when2call:{item['uuid']}", "author": "when2call:benchmark_authors"}
    RULES.apply(item, rec)
    return f"when2call:{original_id}", rec


EXPECTED = {"items": 3652}


def report_extras(records: list[dict]) -> dict:
    """Build the When2Call section of report.json.

    Args:
        records: The valid converted records.

    Returns:
        Reconciliation of the item count, the funnel, and records by option and decision.
    """
    ol = lambda r: r["source"]["original_label"]  # noqa: E731
    return {"reconciliation": {k: {"expected": v, "measured": STATS[k], "ok": STATS[k] == v} for k, v in EXPECTED.items()},
            "funnel": dict(sorted(STATS.items())),
            "by_option_and_decision": dict(Counter(f"{ol(r)['option']}:{r['labels']['decision']}" for r in records))}
