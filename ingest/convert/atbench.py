"""ATBench -> AgentDecisionRecords (one trajectory record per run).

Spec: `datasets.atbench` in label-schema/dataset_mappings.yaml. The two lookup tables are read
from that file, so category translations live in one place.
"""
import json
from collections import Counter
from pathlib import Path

from ..common.paths import mappings
from ..common.record import Record
from ..common.rules import RuleSet
from ..common.text import unquote
from ..common.tools import side_effects

DATASET = "atbench"
RULES = RuleSet(DATASET)


def _table(rule_id: str) -> dict:
    """Read a mapping rule's lookup table from the YAML.

    Args:
        rule_id: Id of a rule with a `table`, e.g. "at.risk_source".

    Returns:
        The table as a dict, exactly as the YAML defines it.

    Raises:
        KeyError: If the rule is not in the ATBench mappings.
    """
    for r in mappings()["datasets"][DATASET]["rules"]:
        if r["id"] == rule_id:
            return r["table"]
    raise KeyError(rule_id)


RISK_SOURCE = _table("at.risk_source")
FAILURE_MODE = _table("at.failure_mode")
INJECTION_SOURCES = {"tool_description_injection"}
# Keys ATBench's generator used to plant content in tool outputs. The planted text stays in input
# (detecting it is the model's job); the giveaway key name is replaced with a neutral one.
MARKER_KEYS = {"_injected_instruction": "note", "_system_warning": "system_warning"}


class UnmappedCategory(ValueError):
    """Raised when a run has a category the mapping tables do not cover.

    The run then becomes a reject rather than a silently wrong record.
    """
    pass


# ---- raw input ---------------------------------------------------------------------------
def iter_source(snapshot: Path):
    """Read every run from the raw snapshot.

    Args:
        snapshot: The ATBench pinned-commit folder.

    Yields:
        `(original_id, run)` pairs: the run id as a string and the raw run dict.
    """
    for run in json.loads((snapshot / "ATBench" / "test.json").read_text(encoding="utf-8")):
        yield str(run["id"]), run


def _tool_call(action: str, thought: str | None) -> dict:
    """Turn an agent action into a schema tool call.

    Args:
        action: The action string, a JSON object with "name" and "arguments".
        thought: The agent's thought for this turn, or None.

    Returns:
        `{"tool_name", "arguments", "reasoning"}`; arguments that are not an object are wrapped as
        `{"value": ...}`.

    Raises:
        json.JSONDecodeError: If the action is not valid JSON.
    """
    call = json.loads(action)
    args = call.get("arguments")
    return {"tool_name": call["name"],
            "arguments": args if isinstance(args, dict) else {"value": args},
            "reasoning": thought}


def _final_answer(action: str) -> str:
    """Extract the response from a final-answer action.

    Args:
        action: An action of the form `Complete{"response": ...}`.

    Returns:
        The response text, unquoted, or the raw payload after "Complete" if it is not JSON.
    """
    payload = action.strip()[len("Complete"):]
    try:
        value = json.loads(payload)
        if isinstance(value, dict) and "response" in value:
            return unquote(str(value["response"]))
    except json.JSONDecodeError:
        pass
    return payload


def _rename_keys(value):
    """Copy a JSON value with generator marker keys renamed at every depth.

    Args:
        value: A parsed JSON value.

    Returns:
        A copy with each MARKER_KEYS key renamed to its neutral name ("additional_<name>" if
        that name already exists, so no real field is overwritten).
    """
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            new = MARKER_KEYS.get(k, k)
            if new in value and new != k:  # never overwrite a real field
                new = f"additional_{new}"
            out[new] = _rename_keys(v)
        return out
    if isinstance(value, list):
        return [_rename_keys(v) for v in value]
    return value


def scrub_agent_text(text: str | None) -> str | None:
    """Replace generator marker key names in agent text with their neutral names.

    Agents sometimes quote the key that carried the planted text (e.g. "a suspicious
    `_injected_instruction` field"); left alone, that name would give the construction away.

    Args:
        text: Agent thought, action or answer text, or None.

    Returns:
        The text with each MARKER_KEYS key replaced by its neutral name, or None for None.
    """
    if text is None:
        return None
    for old, new in MARKER_KEYS.items():
        text = text.replace(old, new)
    return text


def sanitise_tool_output(content: str) -> tuple[str, bool]:
    """Neutralise generator marker keys in a tool output.

    The planted text stays, because detecting it is the model's job; only the giveaway key name
    changes. JSON content is re-serialised with indent 2; other text has the keys replaced.

    Args:
        content: The tool output text.

    Returns:
        `(content, had_marker)`: the sanitised content and whether a marker key was present.
    """
    if not any(f'"{k}"' in content for k in MARKER_KEYS):
        return content, False
    try:
        return json.dumps(_rename_keys(json.loads(content)), indent=2, ensure_ascii=False), True
    except json.JSONDecodeError:
        for old, new in MARKER_KEYS.items():
            content = content.replace(f'"{old}"', f'"{new}"')
        return content, True


def build_input(run: dict) -> tuple[dict, list[int]]:
    """Build the record's `input` from a raw run.

    Maps turns to messages (user -> principal, agent -> assistant with a tool call or final
    answer, environment -> tool output), sanitises tool outputs, and copies tools without the
    leaky `_source` / `_original_description` fields.

    Args:
        run: A raw ATBench run.

    Returns:
        `(input, marked)`: the input dict and the indexes of messages that carried a generator
        marker key.

    Raises:
        ValueError: If a turn has an unknown role.
    """
    messages, last_tool, marked = [], None, []
    for turn in run["contents"][0]:
        role = turn["role"]
        if role == "user":
            messages.append({"role": "user", "content": turn["content"], "trust": "principal"})
        elif role == "agent":
            thought = scrub_agent_text(unquote(turn.get("thought") or "") or None)
            action = scrub_agent_text((turn.get("action") or "").strip())
            if action.startswith("{"):
                call = _tool_call(action, thought)
                last_tool = call["tool_name"]
                messages.append({"role": "assistant", "content": thought or "", "trust": "agent_generated",
                                 "tool_call": call})
            elif action.startswith("Complete"):
                messages.append({"role": "assistant", "content": _final_answer(action),
                                 "trust": "agent_generated"})
            else:
                messages.append({"role": "assistant", "content": action, "trust": "agent_generated"})
        elif role == "environment":
            content = turn["content"] if isinstance(turn["content"], str) else json.dumps(turn["content"])
            content, had_marker = sanitise_tool_output(content)
            if had_marker:
                marked.append(len(messages))
            messages.append({"role": "tool", "content": content, "trust": "tool_output", "tool_name": last_tool})
        else:
            raise ValueError(f"unknown role {role!r}")

    # Only name / description / parameters: `_source` and `_original_description` would leak the answer.
    tools = [{"name": t["name"], "description": t.get("description"),
              "parameters_schema": t.get("parameters") if isinstance(t.get("parameters"), dict) else None,
              "origin": "first_party", "side_effects": side_effects(t["name"])}
             for t in run["tool_used"]]
    first_user = next((m["content"] for m in messages if m["role"] == "user"), None)
    return ({"system_prompt": None, "user_prompt": first_user, "messages": messages,
             "tools_available": tools, "planned_action": None, "principal": None, "modality": "text"}, marked)


# ---- rules (registration order = application order) ---------------------------------------
@RULES.rule("at.risk_source")
def risk_source(run, rec: Record) -> bool:
    """at.risk_source: set attack_vector and add failure modes from the risk-source table.

    Args:
        run: The raw run.
        rec: The Record being built.

    Returns:
        True (applies to every run).

    Raises:
        UnmappedCategory: If the run's risk_source is not in the table.
    """
    if run["risk_source"] not in RISK_SOURCE:
        raise UnmappedCategory(f"risk_source {run['risk_source']!r}")
    entry = RISK_SOURCE[run["risk_source"]]
    if entry["attack_vector"] is not None:
        rec.set("attack_vector", entry["attack_vector"], "given", "at.risk_source")
    rec.add_modes(entry["failure_modes"], "given", "at.risk_source")
    return True


@RULES.rule("at.failure_mode")
def failure_mode(run, rec: Record) -> bool:
    """at.failure_mode: add failure modes from the failure-mode table, on unsafe runs only.

    Args:
        run: The raw run.
        rec: The Record being built.

    Returns:
        True if the run is unsafe and modes were looked up, otherwise False.

    Raises:
        UnmappedCategory: If an unsafe run's failure_mode is not in the table.
    """
    if run["label"] != 1:
        return False
    if run["failure_mode"] not in FAILURE_MODE:
        raise UnmappedCategory(f"failure_mode {run['failure_mode']!r}")
    rec.add_modes(FAILURE_MODE[run["failure_mode"]], "given", "at.failure_mode")
    return True


@RULES.rule("at.poisoned_tool")
def poisoned_tool(run, rec: Record) -> bool:
    """at.poisoned_tool: mark poisoned tools in tool-description-injection runs.

    Tools that carry `_original_description` are the ones whose description was altered; they
    become `{"kind": "tool", "tool_name": ...}` adversarial locations.

    Args:
        run: The raw run.
        rec: The Record being built.

    Returns:
        True if at least one poisoned tool was marked, otherwise False.
    """
    if run["risk_source"] not in INJECTION_SOURCES:
        return False
    locations = [{"kind": "tool", "tool_name": t["name"]} for t in run["tool_used"] if "_original_description" in t]
    if not locations:
        return False
    rec.set("adversarial_locations", locations, "given", "at.poisoned_tool")
    return True


@RULES.rule("at.marked_tool_output")
def marked_tool_output(run, rec: Record) -> bool:
    """at.marked_tool_output: mark tool messages that carried a generator marker key.

    Uses the indexes `build_input` stored in `rec.scratch["marked_messages"]`. Locations from
    at.poisoned_tool on the same run are kept.

    Args:
        run: The raw run (unused; the marks come from the built input).
        rec: The Record being built.

    Returns:
        True if at least one message was marked, otherwise False.
    """
    marked = rec.scratch.get("marked_messages", [])
    if not marked:
        return False
    locations = [{"kind": "message", "message_index": i} for i in marked]
    if rec.labels["adversarial_locations"]:  # both kinds in one run: keep both, credit both rules
        locations = rec.labels["adversarial_locations"] + locations
        rec.set("adversarial_locations", locations, "given", "at.poisoned_tool+at.marked_tool_output")
    else:
        rec.set("adversarial_locations", locations, "given", "at.marked_tool_output")
    return True


@RULES.rule("at.safe")
def safe(run, rec: Record) -> bool:
    """at.safe: a safe run (label 0) becomes ALLOW.

    Failure modes are set to verified empty unless the risk source already added one.

    Args:
        run: The raw run.
        rec: The Record being built.

    Returns:
        True if the run is safe, otherwise False.
    """
    if run["label"] != 0:
        return False
    rec.set("decision", "ALLOW", "given", "at.safe")
    rec.set_no_modes("given", "at.safe")  # only takes effect if the risk source added no mode
    return True


@RULES.rule("at.unsafe")
def unsafe(run, rec: Record) -> bool:
    """at.unsafe: an unsafe run (label 1) becomes BLOCK.

    Args:
        run: The raw run.
        rec: The Record being built.

    Returns:
        True if the run is unsafe, otherwise False.
    """
    if run["label"] != 1:
        return False
    rec.set("decision", "BLOCK", "given", "at.unsafe")
    return True


@RULES.rule("at.hard_negative")
def hard_negative(run, rec: Record) -> bool:
    """at.hard_negative: a safe run that contains an attack is a hard negative.

    Args:
        run: The raw run.
        rec: The Record being built (attack_vector must already be set).

    Returns:
        True if the run is safe and its attack_vector is set and not "none", otherwise False.
    """
    if run["label"] != 0 or rec.labels["attack_vector"] in (None, "none"):
        return False
    rec.set("hard_negative", True, "given", "at.hard_negative")
    return True


# ---- record --------------------------------------------------------------------------------
def to_record(original_id: str, run: dict, revision: str) -> tuple[str, Record]:
    """Convert one ATBench run into a Record.

    Fills `source` (including group_ids and the original labels), builds `input`, and applies
    every rule.

    Args:
        original_id: The run id as a string.
        run: The raw run.
        revision: The raw snapshot's commit, written to `source.dataset_version`.

    Returns:
        `(record_id, record)`: "atbench:<id>" and the Record, ready for `Record.build`.
    """
    rec = Record(DATASET, original_id, "trajectory")
    rec.source.update({
        "dataset_version": revision,
        "original_split": "test",
        "step_index": None,
        "generator_model": None,
        "license": "Apache-2.0",
        "original_label": {k: run[k] for k in ("label", "risk_source", "failure_mode", "real_world_harm", "reason")},
    })
    rec.source["group_ids"] = {
        "task": f"atbench:{original_id}",
        "attack": f"atbench:{run['risk_source']}" if run["risk_source"] != "benign" else None,
        "trajectory": f"atbench:{original_id}",
        "author": "atbench:benchmark_authors",
    }
    rec.input, rec.scratch["marked_messages"] = build_input(run)
    RULES.apply(run, rec)
    return f"atbench:{original_id}", rec


# ---- dataset-specific report section ---------------------------------------------------------
EXPECTED = {"records": 1000, "safe": 503, "unsafe": 497, "benign_runs": 250, "poisoned_tool_runs": 102,
            "marked_tool_messages": 88}


def report_extras(records: list[dict]) -> dict:
    """Build the ATBench section of report.json.

    Args:
        records: The valid converted records.

    Returns:
        A dict with: reconciliation (each count vs. its expected raw value), hard negatives by
        risk source, unsafe runs left without failure modes, message-role counts, the number of
        assistant tool calls, and the tool side-effect distribution.
    """
    C = Counter
    checks = {
        "records": len(records),
        "safe": sum(r["labels"]["decision"] == "ALLOW" for r in records),
        "unsafe": sum(r["labels"]["decision"] == "BLOCK" for r in records),
        "benign_runs": sum(r["source"]["original_label"]["risk_source"] == "benign" for r in records),
        "poisoned_tool_runs": sum(any(loc["kind"] == "tool" for loc in r["labels"]["adversarial_locations"] or [])
                                  for r in records),
        "marked_tool_messages": sum(sum(loc["kind"] == "message" for loc in r["labels"]["adversarial_locations"] or [])
                                    for r in records),
    }
    return {
        "reconciliation": {k: {"expected": EXPECTED[k], "got": v, "ok": EXPECTED[k] == v} for k, v in checks.items()},
        "hard_negatives_by_risk_source": dict(C(r["source"]["original_label"]["risk_source"]
                                                for r in records if r["labels"]["hard_negative"])),
        "unsafe_without_modes_by_category": dict(C(
            f'{r["source"]["original_label"]["risk_source"]} / {r["source"]["original_label"]["failure_mode"]}'
            for r in records if r["labels"]["decision"] == "BLOCK" and not r["labels"]["failure_modes"])),
        "message_roles": dict(C(m["role"] for r in records for m in r["input"]["messages"])),
        "assistant_turns_with_tool_call": sum(1 for r in records for m in r["input"]["messages"] if m.get("tool_call")),
        "tool_side_effects": dict(C(t["side_effects"] for r in records for t in r["input"]["tools_available"])),
    }
