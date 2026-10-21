"""ATBench runs unrolled into step records (PROACT), from a pinned boundaries run.

Spec: `datasets.atbench_steps` in label-schema/dataset_mappings.yaml. Input: the pinned run folder
data/derived/atbench_steps/<run>/ (boundaries.jsonl from `python -m generate proact`, and
human.jsonl once the human check is imported) plus the raw ATBench snapshot it was made from.

Safe run: every decision point is ALLOW. Unsafe run with a boundary: decision points before it are
ALLOW, the boundary is BLOCK, later ones are dropped. Unsafe runs without a single boundary (or with
the judges unresolved) give no records. Records follow their parent run's split (role: derived).
"""
import json
from collections import Counter
from pathlib import Path

from ..common.io import read_jsonl
from ..common.paths import raw_snapshot
from ..common.record import Record
from ..common.rules import RuleSet
from . import atbench

DATASET = "atbench_steps"
RULES = RuleSet(DATASET)
STATS: Counter = Counter()
BOUNDARY_RULE = {"marker": "as.boundary_marker", "judges": "as.boundary_judges", "human": "as.boundary_human"}
BOUNDARY_ORIGIN = {"marker": "rule_inferred", "judges": "model_inferred", "human": "human_verified"}


def resolve_boundary(row: dict, human: dict | None) -> tuple[int | None, str | None]:
    """Combine the located boundary with the human check.

    Args:
        row: A boundaries.jsonl row.
        human: The human.jsonl row for the same run, or None.

    Returns:
        `(message index, method)`: method is "human" when a reviewer confirmed or corrected it,
        else the located method ("marker" / "judges"); `(None, None)` when the run has no single
        boundary or it is unresolved.
    """
    if human is not None:
        return (None, None) if human["no_single_boundary"] else (human["boundary"], "human")
    if row["method"] in ("marker", "judges"):
        return row["boundary"], row["method"]
    return None, None


# ---- raw input ---------------------------------------------------------------------------
def iter_source(snapshot: Path):
    """Yield one item per decision point to keep.

    Args:
        snapshot: The pinned atbench_steps run folder.

    Yields:
        `(original_id, item)`: original_id is "<run id>:<message index>"; item holds the run, its
        built input, the decision point, the step's role (safe / before / boundary) and the method.

    Raises:
        RuntimeError: If the run was made from a different ATBench snapshot than the one present.
    """
    STATS.clear()
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    raw = raw_snapshot("atbench")
    revision = json.loads((raw / "manifest.json").read_text(encoding="utf-8"))["revision"]
    if manifest["parents"]["atbench"] != revision:
        raise RuntimeError(f"boundaries were located on ATBench {manifest['parents']['atbench']}, not {revision}")
    runs = dict(atbench.iter_source(raw))
    human = {h["run_id"]: h for h in read_jsonl(snapshot / "human.jsonl")}
    for row in read_jsonl(snapshot / "boundaries.jsonl"):
        run = runs[row["run_id"]]
        built, marked = atbench.build_input(run)
        STATS[f"runs_{row['method']}"] += 1
        if row["label"] == 0:
            steps = [(p, "safe", None) for p in row["decision_points"]]
        else:
            boundary, method = resolve_boundary(row, human.get(row["run_id"]))
            if boundary is None:
                STATS["unsafe_runs_without_boundary"] += 1
                continue
            STATS[f"boundary_{method}"] += 1
            steps = [(p, "before", method) for p in row["decision_points"] if p < boundary] + [(boundary, "boundary", method)]
        for point, role, method in steps:
            yield f"{row['run_id']}:{point}", {"run_id": row["run_id"], "run": run, "built": built, "marked": marked,
                                               "point": point, "role": role, "method": method}


# ---- rules ---------------------------------------------------------------------------------
@RULES.rule("as.safe_run")
def safe_run(item, rec: Record) -> bool:
    """as.safe_run: every decision point of a safe run is ALLOW.

    Args:
        item: The source item.
        rec: The Record being built.

    Returns:
        True for steps of safe runs.
    """
    if item["role"] != "safe":
        return False
    rec.set("decision", "ALLOW", "rule_inferred", "as.safe_run")
    rec.set_no_modes("rule_inferred", "as.safe_run")
    return True


@RULES.rule("as.before_boundary")
def before_boundary(item, rec: Record) -> bool:
    """as.before_boundary: decision points before an unsafe run's boundary are ALLOW.

    Args:
        item: The source item.
        rec: The Record being built.

    Returns:
        True for steps before the boundary.
    """
    if item["role"] != "before":
        return False
    rec.set("decision", "ALLOW", "rule_inferred", "as.before_boundary")
    rec.set_no_modes("rule_inferred", "as.before_boundary")
    return True


def _boundary(item, rec: Record, method: str) -> bool:
    """Set BLOCK and the parent run's failure modes on a boundary located by `method`.

    Args:
        item: The source item.
        rec: The Record being built.
        method: "marker", "judges" or "human".

    Returns:
        True if the item is a boundary located by that method.

    Raises:
        atbench.UnmappedCategory: If the run's categories are not in ATBench's tables.
    """
    if item["role"] != "boundary" or item["method"] != method:
        return False
    rule, origin = BOUNDARY_RULE[method], BOUNDARY_ORIGIN[method]
    run = item["run"]
    if run["risk_source"] not in atbench.RISK_SOURCE or run["failure_mode"] not in atbench.FAILURE_MODE:
        raise atbench.UnmappedCategory(f"{run['risk_source']} / {run['failure_mode']}")
    rec.set("decision", "BLOCK", origin, rule)
    rec.add_modes(atbench.RISK_SOURCE[run["risk_source"]]["failure_modes"] + atbench.FAILURE_MODE[run["failure_mode"]],
                  origin, rule)
    return True


@RULES.rule("as.boundary_marker")
def boundary_marker(item, rec: Record) -> bool:
    """as.boundary_marker: BLOCK at a boundary located by rule (single action, or single after the planting).

    Args:
        item: The source item.
        rec: The Record being built.

    Returns:
        True if it applied.
    """
    return _boundary(item, rec, "marker")


@RULES.rule("as.boundary_judges")
def boundary_judges(item, rec: Record) -> bool:
    """as.boundary_judges: BLOCK at a boundary the LLM judges agreed on.

    Args:
        item: The source item.
        rec: The Record being built.

    Returns:
        True if it applied.
    """
    return _boundary(item, rec, "judges")


@RULES.rule("as.boundary_human")
def boundary_human(item, rec: Record) -> bool:
    """as.boundary_human: BLOCK at a boundary a human confirmed or corrected.

    Args:
        item: The source item.
        rec: The Record being built.

    Returns:
        True if it applied.
    """
    return _boundary(item, rec, "human")


@RULES.rule("as.attack_visible")
def attack_visible(item, rec: Record) -> bool:
    """as.attack_visible: the run's attack labels, limited to what the step's history shows.

    Benign runs get attack_vector "none". Otherwise the attack is visible when a poisoned tool is in
    the tool list, a planted tool output is in the history, or the vector is the user's own turn;
    then attack_vector and the visible adversarial locations are set, and an ALLOW step is a hard
    negative. An attack not yet visible (or not locatable) leaves attack_vector unknown (null).

    Args:
        item: The source item.
        rec: The Record being built.

    Returns:
        True if attack labels were set.
    """
    vector = atbench.RISK_SOURCE[item["run"]["risk_source"]]["attack_vector"]
    if vector in (None, "none"):
        if item["run"]["risk_source"] == "benign":
            rec.set("attack_vector", "none", "given", "as.attack_visible")
            rec.set("adversarial_locations", [], "given", "as.attack_visible")
            return True
        return False
    locations = [{"kind": "message", "message_index": i} for i in item["marked"] if i < item["point"]]
    if item["run"]["risk_source"] in atbench.INJECTION_SOURCES:
        locations += [{"kind": "tool", "tool_name": t["name"]} for t in item["run"]["tool_used"] if "_original_description" in t]
    if not locations and vector != "direct_user":
        return False
    rec.set("attack_vector", vector, "given", "as.attack_visible")
    rec.set("adversarial_locations", locations, "given", "as.attack_visible")
    if rec.labels["decision"] == "ALLOW":
        rec.set("hard_negative", True, "given", "as.attack_visible")
    return True


# ---- record --------------------------------------------------------------------------------
def to_record(original_id: str, item: dict, revision: str) -> tuple[str, Record]:
    """Convert one decision point of an ATBench run into a step Record.

    Args:
        original_id: "<run id>:<message index>".
        item: The source item.
        revision: The boundaries run's revision.

    Returns:
        `(record_id, record)`: "atbench_steps:" + original_id and the Record.
    """
    built, point = item["built"], item["point"]
    rec = Record(DATASET, original_id, "step")
    message = built["messages"][point]
    action = message["tool_call"] if message.get("tool_call") else \
        {"tool_name": "final_answer", "arguments": {"text": message.get("content") or ""}, "reasoning": None}
    rec.input = {**built, "messages": built["messages"][:point], "planned_action": action}
    run = item["run"]
    rec.source.update({
        "dataset_version": revision, "original_split": "test", "step_index": point, "generator_model": None,
        "license": "Apache-2.0 (derived from ATBench)",
        "original_label": {"run_label": run["label"], "risk_source": run["risk_source"], "failure_mode": run["failure_mode"],
                           "step_role": item["role"], "boundary_method": item["method"]},
        "derived_from": [{"dataset": "atbench", "role": "parent", "record_id": f"atbench:{item['run_id']}", "key": None}],
    })
    rec.source["group_ids"] = {
        "task": f"atbench:{item['run_id']}",
        "attack": f"atbench:{run['risk_source']}" if run["risk_source"] != "benign" else None,
        "trajectory": f"atbench:{item['run_id']}",
        "author": "atbench:benchmark_authors",
    }
    rec.meta = {"generation": {"family": "proact_unroll", "run": revision.split(":")[0], "operator": None,
                               "branch": item["role"], "side": None, "generator_model": None, "judge_model": None,
                               "prompt_version": None, "judge_scores": None}}
    RULES.apply(item, rec)
    return f"atbench_steps:{original_id}", rec


def report_extras(records: list[dict]) -> dict:
    """Build the atbench_steps section of report.json.

    Args:
        records: The valid converted records.

    Returns:
        Run counts by boundary method, step records by role and decision, and final-answer BLOCKs.
    """
    ol = lambda r: r["source"]["original_label"]  # noqa: E731
    return {
        "runs": dict(sorted(STATS.items())),
        "steps_by_role": dict(Counter(ol(r)["step_role"] for r in records)),
        "steps_by_decision": dict(Counter(r["labels"]["decision"] for r in records)),
        "boundary_by_method": dict(Counter(ol(r)["boundary_method"] for r in records if ol(r)["step_role"] == "boundary")),
        "final_answer_blocks": sum(r["input"]["planned_action"]["tool_name"] == "final_answer"
                                   and r["labels"]["decision"] == "BLOCK" for r in records),
    }
