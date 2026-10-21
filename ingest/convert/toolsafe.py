"""ToolSafe (TS-Bench) -> AgentDecisionRecords (one step record per planned tool call).

Spec: `datasets.toolsafe` in label-schema/dataset_mappings.yaml. ToolSafe stores histories and
actions as ReAct text; `ingest.common.react` parses them into messages and tool calls.
"""
import json
import re
from collections import Counter
from pathlib import Path

from ..common.react import parse_history, parse_step
from ..common.record import Record
from ..common.rules import RuleSet
from ..common.text import normalise, sha1_12, task_key
from ..common.tools import parse_tool_text, side_effects

DATASET = "toolsafe"
RULES = RuleSet(DATASET)

ORIGINS = {"agentdojo-traj": "agentdojo", "agentharm-traj": "agentharm", "asb-traj": "asb"}
# file stem -> (ASB attack type, whether the type is inferred rather than given by the file name)
ASB_TYPES = {"DPI_attack_success": ("DPI", False), "OPI_attack_success": ("OPI", False),
             "atttack_failure": ("OPI", True)}
# The benchmarks' own attack templates; they stay in input as content and are used to locate attacks.
AGENTDOJO_INJECTION = re.compile(r"<INFORMATION>.*?(?:</INFORMATION>|$)", re.S)
ASB_DPI = re.compile(r"You must strictly adhere to the following instruction")
ASB_OPI = re.compile(r"Now you need to pay attention to the following request")
# AgentHarm's environment folder names ("harmful_toolscontent", ...) appear in tool error messages and
# would give the label away; they are replaced with a neutral folder.
AGENTHARM_ENV_PATH = re.compile(r"benchmark/agentharm/environments/[A-Za-z_]+/")


# ---- raw input ---------------------------------------------------------------------------
def iter_source(snapshot: Path):
    """Read every step from the raw snapshot, in a stable order.

    Args:
        snapshot: The ToolSafe pinned-commit folder.

    Yields:
        `(original_id, step)` pairs. original_id is "<path under TS-Bench>#<row index>" (the
        dataset's own ids are not unique). The step dict gets "_path", "_index", "_origin",
        "_suite", "_stem", "_asb_type" and "_asb_type_inferred" keys derived from its location.
    """
    root = snapshot / "TS-Bench"
    for path in sorted(root.rglob("*.json")):
        rel = path.relative_to(root).as_posix()
        origin = ORIGINS[rel.split("/")[0]]
        asb_type, inferred = ASB_TYPES.get(path.stem, (None, False))
        for i, step in enumerate(json.loads(path.read_text(encoding="utf-8"))):
            yield f"{rel}#{i}", dict(step, _path=rel, _index=i, _origin=origin, _stem=path.stem,
                                    _suite=path.stem if origin == "agentdojo" else "all",
                                    _asb_type=asb_type, _asb_type_inferred=inferred)


def clean_instruction(instruction: str) -> str:
    """Remove an ASB DPI suffix, so an attacked task hashes to the same task key as the clean one.

    Args:
        instruction: The step's instruction.

    Returns:
        The instruction up to "You must strictly adhere to the following instruction", or unchanged.
    """
    m = ASB_DPI.search(instruction)
    return instruction[:m.start()].strip() if m else instruction


def _assistant_message(parsed: dict) -> dict:
    """Turn one parsed ReAct step into an assistant message.

    Args:
        parsed: A step from `react.parse_step`.

    Returns:
        An assistant message with the tool call (thought as reasoning), or with the final answer /
        thought as content when there is no tool call.
    """
    if parsed["tool_call"]:
        return {"role": "assistant", "content": "", "trust": "agent_generated",
                "tool_call": dict(parsed["tool_call"], reasoning=parsed["thought"])}
    content = parsed["final_answer"] if parsed["final_answer"] is not None else (parsed["thought"] or "")
    return {"role": "assistant", "content": content, "trust": "agent_generated"}


def planned_action(current_action: str) -> dict:
    """Parse the step being judged into the record's planned action.

    Args:
        current_action: The step's `current_action` text.

    Returns:
        `{"tool_name", "arguments", "reasoning"}`. A final answer becomes the pseudo-call
        `final_answer` with arguments {"text": ...}.

    Raises:
        ValueError: If the text holds neither a tool call nor a final answer.
    """
    parsed = parse_step(current_action)
    if parsed["tool_call"]:
        return dict(parsed["tool_call"], reasoning=parsed["thought"])
    if parsed["final_answer"] is not None:
        return {"tool_name": "final_answer", "arguments": {"text": parsed["final_answer"]},
                "reasoning": parsed["thought"]}
    raise ValueError("current_action has neither a tool call nor a final answer")


def build_input(step: dict) -> dict:
    """Build the record's `input` from a raw step.

    Args:
        step: A raw ToolSafe step (with the derived keys from `iter_source`).

    Returns:
        The input dict: the instruction as the user turn, then an assistant message and (if any)
        a tool-output message per history step (AgentHarm environment paths neutralised), the
        parsed tools, and the planned action.

    Raises:
        ValueError: If the current action cannot be parsed (see `planned_action`).
    """
    messages = [{"role": "user", "content": step["instruction"], "trust": "principal"}]
    for parsed in parse_history(step["history"]):
        msg = None
        if parsed["tool_call"] or parsed["final_answer"] is not None or parsed["thought"]:
            msg = _assistant_message(parsed)
            messages.append(msg)  # a bare leading "Observation:" has no assistant turn
        if parsed["observation"] is not None:
            tool = (msg or {}).get("tool_call", {}).get("tool_name")
            observation = AGENTHARM_ENV_PATH.sub("data/", parsed["observation"])
            messages.append({"role": "tool", "content": observation, "trust": "tool_output", "tool_name": tool})
    tools = [dict(t, origin="first_party", side_effects=side_effects(t["name"])) for t in parse_tool_text(step["env_info"])]
    return {"system_prompt": None, "user_prompt": step["instruction"], "messages": messages,
            "tools_available": tools, "planned_action": planned_action(step["current_action"]),
            "principal": None, "modality": "text"}


def _spans(messages: list[dict], pattern: re.Pattern, role: str) -> list[dict]:
    """Locate an attack template in messages of one role.

    Args:
        messages: The input messages.
        pattern: The template to find.
        role: "user" or "tool".

    Returns:
        One `{"kind": "message", "message_index", "start", "end"}` per message containing the
        template; the span runs from the template to the end of its block (AgentDojo) or message.
    """
    out = []
    for i, m in enumerate(messages):
        if m["role"] != role:
            continue
        hit = pattern.search(m["content"])
        if hit:
            end = hit.end() if pattern is AGENTDOJO_INJECTION else len(m["content"])
            out.append({"kind": "message", "message_index": i, "start": hit.start(), "end": end})
    return out


# ---- rules (registration order = application order) ---------------------------------------
@RULES.rule("ts.safe")
def safe(step, rec: Record) -> bool:
    """ts.safe: score 0 becomes ALLOW, serving the user's task.

    Args:
        step: The raw step.
        rec: The Record being built.

    Returns:
        True if the score is 0, otherwise False.
    """
    if float(step["score"]) != 0:
        return False
    rec.set("decision", "ALLOW", "given", "ts.safe")
    rec.set("action_relation", "user_task", "given", "ts.safe")
    return True


@RULES.rule("ts.controversial")
def controversial(step, rec: Record) -> bool:
    """ts.controversial: score 0.5 becomes REVIEW.

    Args:
        step: The raw step.
        rec: The Record being built.

    Returns:
        True if the score is 0.5, otherwise False.
    """
    if float(step["score"]) != 0.5:
        return False
    rec.set("decision", "REVIEW", "given", "ts.controversial")
    return True


@RULES.rule("ts.unsafe")
def unsafe(step, rec: Record) -> bool:
    """ts.unsafe: score 1 becomes BLOCK.

    Args:
        step: The raw step.
        rec: The Record being built.

    Returns:
        True if the score is 1, otherwise False.
    """
    if float(step["score"]) != 1:
        return False
    rec.set("decision", "BLOCK", "given", "ts.unsafe")
    return True


@RULES.rule("ts.agentdojo.injection")
def agentdojo_injection(step, rec: Record) -> bool:
    """ts.agentdojo.injection: an AgentDojo <INFORMATION> block in a tool output (mode 16).

    Args:
        step: The raw step.
        rec: The Record being built.

    Returns:
        True if the step is from AgentDojo and an injection is already in its context, else False.
    """
    if step["_origin"] != "agentdojo":
        return False
    spans = _spans(rec.input["messages"], AGENTDOJO_INJECTION, "tool")
    if not spans:
        return False
    rec.set("attack_vector", "tool_output", "by_construction", "ts.agentdojo.injection")
    rec.add_modes([16], "by_construction", "ts.agentdojo.injection")
    rec.set("adversarial_locations", spans, "by_construction", "ts.agentdojo.injection")
    rec.scratch["injected"] = True
    return True


@RULES.rule("ts.agentdojo.clean")
def agentdojo_clean(step, rec: Record) -> bool:
    """ts.agentdojo.clean: an AgentDojo step taken before any injection reached the context.

    Args:
        step: The raw step.
        rec: The Record being built.

    Returns:
        True if the step is from AgentDojo and has no injection in context, otherwise False.
    """
    if step["_origin"] != "agentdojo" or rec.scratch.get("injected"):
        return False
    rec.set("attack_vector", "none", "rule_inferred", "ts.agentdojo.clean")
    rec.set_no_modes("rule_inferred", "ts.agentdojo.clean")
    rec.set("adversarial_locations", [], "rule_inferred", "ts.agentdojo.clean")
    return True


@RULES.rule("ts.agentdojo.injection_block")
def agentdojo_injection_block(step, rec: Record) -> bool:
    """ts.agentdojo.injection_block: an unsafe AgentDojo step under injection serves the injected task.

    Args:
        step: The raw step.
        rec: The Record being built.

    Returns:
        True if the step is from AgentDojo, has an injection in context and scores 1, else False.
    """
    if step["_origin"] != "agentdojo" or not rec.scratch.get("injected") or float(step["score"]) != 1:
        return False
    rec.set("action_relation", "injected_task", "rule_inferred", "ts.agentdojo.injection_block")
    rec.add_modes([22], "rule_inferred", "ts.agentdojo.injection_block")
    return True


@RULES.rule("ts.asb.dpi")
def asb_dpi(step, rec: Record) -> bool:
    """ts.asb.dpi: an ASB direct prompt injection appended to the instruction (mode 2).

    Args:
        step: The raw step.
        rec: The Record being built.

    Returns:
        True if the step is from the DPI file, otherwise False.
    """
    if step["_asb_type"] != "DPI":
        return False
    rec.set("attack_vector", "direct_user", "given", "ts.asb.dpi")
    rec.add_modes([2], "given", "ts.asb.dpi")
    return True


@RULES.rule("ts.asb.opi_seen")
def asb_opi_seen(step, rec: Record) -> bool:
    """ts.asb.opi_seen: an ASB observation injection already in a tool output (mode 16).

    The origin is "given" for the OPI file and "rule_inferred" for the failed-attack file, whose
    OPI type is inferred.

    Args:
        step: The raw step.
        rec: The Record being built.

    Returns:
        True if the step is OPI-type and the injected request is in its context, otherwise False.
    """
    if step["_asb_type"] != "OPI" or not _spans(rec.input["messages"], ASB_OPI, "tool"):
        return False
    origin = "rule_inferred" if step["_asb_type_inferred"] else "given"
    rec.set("attack_vector", "tool_output", origin, "ts.asb.opi_seen")
    rec.add_modes([16], origin, "ts.asb.opi_seen")
    return True


@RULES.rule("ts.asb.opi_not_seen")
def asb_opi_not_seen(step, rec: Record) -> bool:
    """ts.asb.opi_not_seen: an OPI-type step before the injection arrives; the hostile element is the
    attacker's tool in the tool list (mode 18).

    Args:
        step: The raw step.
        rec: The Record being built.

    Returns:
        True if the step is OPI-type and the injected request is not yet in context, otherwise False.
    """
    if step["_asb_type"] != "OPI" or rec.labels["attack_vector"] is not None:
        return False
    rec.set("attack_vector", "tool_metadata", "by_construction", "ts.asb.opi_not_seen")
    rec.add_modes([18], "by_construction", "ts.asb.opi_not_seen")
    return True


@RULES.rule("ts.asb.locations")
def asb_locations(step, rec: Record) -> bool:
    """ts.asb.locations: the attacker's tool plus the DPI suffix or OPI request spans.

    Args:
        step: The raw step.
        rec: The Record being built.

    Returns:
        True for every ASB step, otherwise False.
    """
    if step["_origin"] != "asb":
        return False
    messages = rec.input["messages"]
    locations = _spans(messages, ASB_DPI, "user") + _spans(messages, ASB_OPI, "tool")
    if any(t["name"] == step["attacker_tool"] for t in rec.input["tools_available"]):
        locations.append({"kind": "tool", "tool_name": step["attacker_tool"]})
    rec.set("adversarial_locations", locations, "by_construction", "ts.asb.locations")
    return True


@RULES.rule("ts.asb.attacker_call")
def asb_attacker_call(step, rec: Record) -> bool:
    """ts.asb.attacker_call: the planned call is the attacker's tool, so it serves the attack (mode 22).

    Args:
        step: The raw step.
        rec: The Record being built.

    Returns:
        True if the step is from ASB and its planned call is the attacker tool, otherwise False.
    """
    if step["_origin"] != "asb" or rec.input["planned_action"]["tool_name"] != step["attacker_tool"]:
        return False
    rec.set("action_relation", "injected_task", "by_construction", "ts.asb.attacker_call")
    rec.add_modes([22], "by_construction", "ts.asb.attacker_call")
    return True


@RULES.rule("ts.agentharm.harmful")
def agentharm_harmful(step, rec: Record) -> bool:
    """ts.agentharm.harmful: an AgentHarm harmful request from the user (principal misuse).

    Args:
        step: The raw step.
        rec: The Record being built.

    Returns:
        True if the step is from AgentHarm's harmful file, otherwise False.
    """
    if step["_origin"] != "agentharm" or step["_stem"] != "harmful_steps":
        return False
    rec.set("attack_vector", "none", "given", "ts.agentharm.harmful")
    rec.add_modes(["principal_misuse"], "given", "ts.agentharm.harmful")
    rec.set("action_relation", "harmful_user_task", "given", "ts.agentharm.harmful")
    rec.set("adversarial_locations", [], "given", "ts.agentharm.harmful")
    return True


@RULES.rule("ts.agentharm.benign")
def agentharm_benign(step, rec: Record) -> bool:
    """ts.agentharm.benign: an AgentHarm benign request: no attack, no failure mode.

    Args:
        step: The raw step.
        rec: The Record being built.

    Returns:
        True if the step is from AgentHarm's benign file, otherwise False.
    """
    if step["_origin"] != "agentharm" or step["_stem"] != "benign_steps":
        return False
    rec.set("attack_vector", "none", "given", "ts.agentharm.benign")
    rec.set_no_modes("given", "ts.agentharm.benign")
    rec.set("adversarial_locations", [], "given", "ts.agentharm.benign")
    return True


@RULES.rule("ts.hard_negative")
def hard_negative(step, rec: Record) -> bool:
    """ts.hard_negative: a safe step (score 0) taken with an attack present.

    Args:
        step: The raw step.
        rec: The Record being built (attack_vector must already be set).

    Returns:
        True if the score is 0 and attack_vector is set and not "none", otherwise False.
    """
    if float(step["score"]) != 0 or rec.labels["attack_vector"] in (None, "none"):
        return False
    rec.set("hard_negative", True, "given", "ts.hard_negative")
    return True


# ---- record --------------------------------------------------------------------------------
def to_record(original_id: str, step: dict, revision: str) -> tuple[str, Record]:
    """Convert one ToolSafe step into a Record.

    Args:
        original_id: "<path under TS-Bench>#<row index>", from `iter_source`.
        step: The raw step, with the derived keys `iter_source` adds.
        revision: The raw snapshot's commit, written to `source.dataset_version`.

    Returns:
        `(record_id, record)`: "toolsafe:<origin>:<file stem>:<row index>" and the Record, ready
        for `Record.build`.

    Raises:
        ValueError: If the step's current action cannot be parsed.
    """
    rec = Record(DATASET, original_id, "step")
    rec.input = build_input(step)
    origin, stem = step["_origin"], step["_stem"]
    rec.source.update({
        "dataset_version": revision,
        "original_split": "test" if origin in ("asb", "agentharm") else None,
        "step_index": step["id-segment"] if isinstance(step["id-segment"], int) else None,
        "generator_model": None,
        "license": None,
        "original_label": {k: step[k] for k in ("score", "id-interaction", "id-segment", "attacker_tool",
                                                "aggressive", "attack_success") if k in step}
                          | {"file": step["_path"]},
    })
    attack = None
    if origin == "asb":
        attack = f"asb:{step['_asb_type']}/{step['attacker_tool']}"
    elif origin == "agentdojo":
        block = next((AGENTDOJO_INJECTION.search(m["content"]) for m in rec.input["messages"]
                      if m["role"] == "tool" and AGENTDOJO_INJECTION.search(m["content"])), None)
        attack = f"agentdojo:attack:{sha1_12(normalise(block.group(0)))}" if block else None
    rec.source["group_ids"] = {
        "task": task_key(f"{origin}:{step['_suite']}", clean_instruction(step["instruction"])),
        "attack": attack,
        "trajectory": f"toolsafe:{origin}:{stem}:{step['id-interaction']}",
        "author": f"{origin}:benchmark_authors",
    }
    RULES.apply(step, rec)
    return f"toolsafe:{origin}:{stem}:{step['_index']}", rec


# ---- dataset-specific report section ---------------------------------------------------------
EXPECTED = {"records": 7182, "score_0": 3770, "score_0.5": 1781, "score_1": 1631,
            "agentdojo_injected": 673, "asb_dpi": 2293, "asb_opi_seen": 1517, "asb_opi_not_seen": 1421,
            "attacker_tool_calls": 2527, "agentharm_harmful": 525, "agentharm_benign": 206,
            "final_answer_actions": 411, "hard_negatives": 3017}


def report_extras(records: list[dict]) -> dict:
    """Build the ToolSafe section of report.json.

    Args:
        records: The valid converted records.

    Returns:
        A dict with: reconciliation (each count vs. its value measured on the raw files), parse
        statistics (history steps without a tool call, arguments kept raw, planned tool names that
        are not in the tool list), message-role counts and the tool side-effect distribution.
    """
    C = Counter
    prov = lambda r, k: (r["provenance"].get(k) or {}).get("rule")  # noqa: E731
    score = lambda r: float(r["source"]["original_label"]["score"])  # noqa: E731
    checks = {
        "records": len(records),
        "score_0": sum(score(r) == 0 for r in records),
        "score_0.5": sum(score(r) == 0.5 for r in records),
        "score_1": sum(score(r) == 1 for r in records),
        "agentdojo_injected": sum(prov(r, "attack_vector") == "ts.agentdojo.injection" for r in records),
        "asb_dpi": sum(prov(r, "attack_vector") == "ts.asb.dpi" for r in records),
        "asb_opi_seen": sum(prov(r, "attack_vector") == "ts.asb.opi_seen" for r in records),
        "asb_opi_not_seen": sum(prov(r, "attack_vector") == "ts.asb.opi_not_seen" for r in records),
        "attacker_tool_calls": sum(prov(r, "action_relation") == "ts.asb.attacker_call" for r in records),
        "agentharm_harmful": sum(prov(r, "attack_vector") == "ts.agentharm.harmful" for r in records),
        "agentharm_benign": sum(prov(r, "attack_vector") == "ts.agentharm.benign" for r in records),
        "final_answer_actions": sum(r["input"]["planned_action"]["tool_name"] == "final_answer" for r in records),
        "hard_negatives": sum(r["labels"]["hard_negative"] is True for r in records),
    }
    msgs = [m for r in records for m in r["input"]["messages"]]
    calls = [m["tool_call"] for m in msgs if m.get("tool_call")] + [r["input"]["planned_action"] for r in records]
    return {
        "reconciliation": {k: {"expected": EXPECTED[k], "got": v, "ok": EXPECTED[k] == v} for k, v in checks.items()},
        "history_assistant_turns_without_tool_call": sum(1 for m in msgs if m["role"] == "assistant" and not m.get("tool_call")),
        "tool_call_args_kept_raw": sum(list(c["arguments"]) == ["raw"] for c in calls),
        "planned_tool_not_in_tool_list": sum(
            r["input"]["planned_action"]["tool_name"] not in {t["name"] for t in r["input"]["tools_available"]}
            and r["input"]["planned_action"]["tool_name"] != "final_answer" for r in records),
        "message_roles": dict(C(m["role"] for m in msgs)),
        "tool_side_effects": dict(C(t["side_effects"] for r in records for t in r["input"]["tools_available"])),
    }
