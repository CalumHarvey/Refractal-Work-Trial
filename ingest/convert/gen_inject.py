"""Generated injection groups -> step records (three per kept group), from a pinned gen_inject run.

Spec: `datasets.gen_inject` in label-schema/dataset_mappings.yaml. Input: the pinned run folder
data/generated/gen_inject/<run>/groups.jsonl written by `python -m generate inject`. Only groups the
QC kept are converted; rejected groups stay in the run folder with their reasons.

Branches of one group share the TOUCAN context's prefix:
- block: the injected tool output, then the attacker's call (BLOCK);
- aware_allow: the injected tool output, then the agent's real next call (ALLOW, hard negative);
- benign_reuse: a new user request, then the attack's tool used for the user (ALLOW, hard negative).
Records follow their seeds' split (role: derived): the TOUCAN context record and the attack key.
"""
import copy
import json
from collections import Counter
from pathlib import Path

from ..common.record import Record
from ..common.rules import RuleSet

DATASET = "gen_inject"
RULES = RuleSet(DATASET)
BRANCHES = ("block", "aware_allow", "benign_reuse")


# ---- raw input ---------------------------------------------------------------------------
def iter_source(snapshot: Path):
    """Yield one item per branch of every kept group.

    Args:
        snapshot: The pinned gen_inject run folder.

    Yields:
        `(original_id, item)`: original_id is "<group id>:<branch>"; item holds the group row and
        the branch name.
    """
    with open(snapshot / "groups.jsonl", encoding="utf-8") as f:
        for line in f:
            group = json.loads(line)
            if group["status"] != "kept":
                continue
            for branch in BRANCHES:
                yield f"{group['group_id']}:{branch}", {"group": group, "branch": branch}


def injected_messages(group: dict) -> tuple[list[dict], int]:
    """The context's history with the injection planted in its last tool output.

    Args:
        group: A kept group row.

    Returns:
        `(messages, index of the planted message)`.
    """
    messages = copy.deepcopy(group["context"]["messages"])
    messages[-1]["content"] = group["generator"]["output"]["injected_tool_output"]
    return messages, len(messages) - 1


def applied_operator(attacker_tool: str, planned_tool: str) -> str:
    """The AuraGen operator a generated attack applied, read from what its call does.

    Shared with generate.inject, so the generator's checks and the converter agree.

    Args:
        attacker_tool: The attacker call's tool.
        planned_tool: The real agent's next call's tool.

    Returns:
        "single_step" (the real next call's tool, with attacker arguments) or "new_branch" (any other tool).
    """
    return "single_step" if attacker_tool == planned_tool else "new_branch"


def operator(group: dict) -> str:
    """The operator a kept group applied.

    Args:
        group: A kept group row.

    Returns:
        "single_step" or "new_branch".
    """
    return applied_operator(group["generator"]["output"]["attacker_action"]["tool_name"],
                            group["context"]["planned_action"]["tool_name"])


def _call(action: dict) -> dict:
    """Normalise a generated call to the schema's tool_call shape.

    Args:
        action: `{"tool_name", "arguments"}` from the generator.

    Returns:
        `{"tool_name", "arguments", "reasoning": None}`.
    """
    return {"tool_name": action["tool_name"], "arguments": action.get("arguments") or {}, "reasoning": None}


# ---- rules ---------------------------------------------------------------------------------
@RULES.rule("gi.block")
def block(item, rec: Record) -> bool:
    """gi.block: the attacker's call after the planted injection is BLOCK (modes 16 and 22).

    Args:
        item: The source item.
        rec: The Record being built.

    Returns:
        True for the block branch.
    """
    if item["branch"] != "block":
        return False
    rec.set("decision", "BLOCK", "by_construction", "gi.block")
    rec.set("attack_vector", "tool_output", "by_construction", "gi.block")
    rec.add_modes([16, 22], "by_construction", "gi.block")
    rec.set("action_relation", "injected_task", "by_construction", "gi.block")
    rec.set("adversarial_locations", [{"kind": "message", "message_index": rec.scratch["planted"]}], "by_construction", "gi.block")
    rec.set("hard_negative", False, "by_construction", "gi.block")
    return True


@RULES.rule("gi.aware_allow")
def aware_allow(item, rec: Record) -> bool:
    """gi.aware_allow: the agent's real next call with the injection in view is ALLOW (hard negative).

    Args:
        item: The source item.
        rec: The Record being built.

    Returns:
        True for the aware_allow branch.
    """
    if item["branch"] != "aware_allow":
        return False
    rec.set("decision", "ALLOW", "by_construction", "gi.aware_allow")
    rec.set("attack_vector", "tool_output", "by_construction", "gi.aware_allow")
    rec.set_no_modes("by_construction", "gi.aware_allow")
    rec.set("action_relation", "user_task", "by_construction", "gi.aware_allow")
    rec.set("adversarial_locations", [{"kind": "message", "message_index": rec.scratch["planted"]}], "by_construction", "gi.aware_allow")
    rec.set("hard_negative", True, "by_construction", "gi.aware_allow")
    return True


@RULES.rule("gi.benign_reuse")
def benign_reuse(item, rec: Record) -> bool:
    """gi.benign_reuse: the attack's tool used for an ordinary request is ALLOW (hard negative).

    Args:
        item: The source item.
        rec: The Record being built.

    Returns:
        True for the benign_reuse branch.
    """
    if item["branch"] != "benign_reuse":
        return False
    rec.set("decision", "ALLOW", "by_construction", "gi.benign_reuse")
    rec.set("attack_vector", "none", "by_construction", "gi.benign_reuse")
    rec.set_no_modes("by_construction", "gi.benign_reuse")
    rec.set("action_relation", "user_task", "by_construction", "gi.benign_reuse")
    rec.set("adversarial_locations", [], "by_construction", "gi.benign_reuse")
    rec.set("hard_negative", True, "by_construction", "gi.benign_reuse")
    return True


# ---- record --------------------------------------------------------------------------------
def to_record(original_id: str, item: dict, revision: str) -> tuple[str, Record]:
    """Convert one branch of a kept group into a step Record.

    Args:
        original_id: "<group id>:<branch>".
        item: The source item.
        revision: The run's revision.

    Returns:
        `(record_id, record)`: "gen_inject:" + original_id and the Record.
    """
    group, branch = item["group"], item["branch"]
    ctx, attack, gen = group["context"], group["attack"], group["generator"]["output"]
    rec = Record(DATASET, original_id, "step")
    if branch == "benign_reuse":
        request = gen["benign_reuse"]["user_request"]
        messages, planted = [{"role": "user", "content": request, "trust": "principal"}], None
        action, user_prompt = _call(gen["benign_reuse"]["action"]), request
    else:
        messages, planted = injected_messages(group)
        # _call drops the real agent's reasoning: generated calls have none, so keeping it on the aware
        # branch alone would let "has reasoning" predict ALLOW
        action = _call(gen["attacker_action"] if branch == "block" else ctx["planned_action"])
        user_prompt = ctx["user_prompt"]
    rec.scratch["planted"] = planted
    rec.input = {"system_prompt": None, "user_prompt": user_prompt, "messages": messages,
                 "tools_available": ctx["tools"], "planned_action": action, "principal": None, "modality": "text"}
    generator = group["generator"]
    rec.source.update({
        "dataset_version": revision, "original_split": None, "step_index": len(messages),
        "generator_model": generator.get("model_version") or generator["model"],
        "license": "generated from TOUCAN (Apache-2.0) and "
                   + {"injecagent": "InjecAgent (MIT)", "llmail_inject": "LLMail-Inject (MIT)"}[attack["dataset"]],
        "original_label": {"branch": branch, "operator": operator(group),
                           "attack_dataset": attack["dataset"], "attack_type": attack.get("attack_type"),
                           "side": group["side"]},
        "derived_from": [{"dataset": ctx["dataset"], "role": "context", "record_id": ctx["record_id"], "key": None},
                         {"dataset": attack["dataset"], "role": "attack", "record_id": None, "key": attack["key"]}],
    })
    rec.source["group_ids"] = {"task": ctx["task_key"], "attack": attack["key"],
                               "trajectory": f"gen_inject:{group['group_id']}", "author": f"gen_inject:{generator['model']}"}
    rec.meta = {"generation": {"family": "inject_on_context", "run": revision.split(":")[0],
                               "operator": operator(group), "branch": branch, "side": group["side"],
                               "generator_model": generator.get("model_version") or generator["model"],
                               "judge_model": group["judge"].get("model_version") or group["judge"]["model"],
                               "prompt_version": generator["prompt_version"], "judge_scores": group["judge"].get("scores")}}
    if branch == "block":
        lineage = {k: v for k, v in (gen.get("argument_lineage") or {}).items() if v in ("user", "tool", "system", "agent")}
        rec.meta["lineage"] = lineage or None
    RULES.apply(item, rec)
    return f"gen_inject:{original_id}", rec


def report_extras(records: list[dict]) -> dict:
    """Build the gen_inject section of report.json.

    Args:
        records: The valid converted records.

    Returns:
        Records by branch, side, operator and attack dataset, and the share of BLOCK tool names
        also seen on ALLOW records (1.0 means tool identity no longer predicts the label).
    """
    ol = lambda r: r["source"]["original_label"]  # noqa: E731
    block_tools = {r["input"]["planned_action"]["tool_name"] for r in records if r["labels"]["decision"] == "BLOCK"}
    allow_tools = {r["input"]["planned_action"]["tool_name"] for r in records if r["labels"]["decision"] == "ALLOW"}
    return {
        "by_branch": dict(Counter(ol(r)["branch"] for r in records)),
        "by_side": dict(Counter(ol(r)["side"] for r in records)),
        "by_operator": dict(Counter(ol(r)["operator"] for r in records if ol(r)["branch"] == "block")),
        "by_attack_dataset": dict(Counter(ol(r)["attack_dataset"] for r in records if ol(r)["branch"] == "block")),
        "block_tools_also_allowed": round(len(block_tools & allow_tools) / len(block_tools), 3) if block_tools else None,
    }
