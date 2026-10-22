"""Training arms and evaluation sets for the MVP experiment.

Rows come from the training view (data/training/<split>.jsonl, licensed data only) and, for Tier 2,
straight from the processed evaluation-only datasets (data/processed/<dataset>/records.jsonl), which
are never trained on. Only step records are used: the probe is a step-decision probe.

Label: ALLOW -> 0; BLOCK and REVIEW -> 1 (REVIEW maps to block, as in the Jev export).
"""
import json
from collections import Counter
from functools import lru_cache

from ingest.assembly.config import eval_only_datasets
from ingest.common.paths import PROCESSED, TRAINING

REAL_STEP_SOURCES = ("injecagent", "toucan", "toolace", "when2call", "redcode")


@lru_cache(maxsize=None)
def training_rows(split: str) -> tuple[dict, ...]:
    """Load the step rows of one split of the training view.

    Args:
        split: "train", "validation", "test", "holdout" or "diagnostic".

    Returns:
        Step rows (granularity "step"), as a tuple for caching.

    Raises:
        FileNotFoundError: If the training view has not been built.
    """
    path = TRAINING / f"{split}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing; run ingest/build.py")
    with open(path, encoding="utf-8") as f:
        return tuple(r for r in (json.loads(line) for line in f) if r["granularity"] == "step")


@lru_cache(maxsize=None)
def eval_only_rows(dataset: str) -> tuple[dict, ...]:
    """Load the step records of an evaluation-only dataset, shaped like training rows.

    Args:
        dataset: A dataset with `include: eval_only`.

    Returns:
        Rows with record_id, dataset, source, input, decision and aux (hard_negative).

    Raises:
        ValueError: If the dataset is not evaluation-only (licensed data belongs in the training view).
    """
    if dataset not in eval_only_datasets():
        raise ValueError(f"{dataset} is not an eval_only dataset")
    path = PROCESSED / dataset / "records.jsonl"
    if not path.exists():
        return ()
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["granularity"] != "step" or r["labels"]["decision"] is None:
                continue
            origin = r["record_id"].split(":")[1] if dataset == "toolsafe" else dataset
            rows.append({"record_id": r["record_id"], "dataset": dataset, "source": f"{dataset}/{origin}",
                         "input": r["input"], "decision": r["labels"]["decision"], "group_ids": r["source"]["group_ids"],
                         "aux": {"hard_negative": r["labels"]["hard_negative"]}})
    return tuple(rows)


def label(row: dict) -> int:
    """Binary target of a row.

    Args:
        row: A row.

    Returns:
        0 for ALLOW, 1 for BLOCK or REVIEW.
    """
    return 0 if row["decision"] == "ALLOW" else 1


def attack_dataset(row: dict) -> str | None:
    """Name the dataset a generated row's attack came from.

    Args:
        row: A row.

    Returns:
        The namespace of its attack key (e.g. "llmail_inject"), or None.
    """
    key = (row.get("group_ids") or {}).get("attack")
    return key.split(":")[0] if key else None


def _branch(row: dict) -> str | None:
    """Name the generated branch a row comes from, from its decision rule.

    Args:
        row: A gen_inject row.

    Returns:
        "block", "aware_allow" or "benign_reuse".
    """
    rule = (row.get("provenance") or {}).get("decision", {}).get("rule", "")
    return {"gi.block": "block", "gi.aware_allow": "aware_allow", "gi.benign_reuse": "benign_reuse"}.get(rule)


# ---- arms ----------------------------------------------------------------------------------
ARMS = {
    "A0": "Real only, no PROACT: InjecAgent A x A, TOUCAN / ToolACE / When2Call / RedCode train",
    "A": "A0 + ATBench train steps from PROACT",
    "B": "A + all generated records",
    "C": "A + generated BLOCK branches only (no aware-ALLOW, no benign reuse)",
    "D": "B without generated records seeded by LLMail-Inject",
}


def arm_rows(arm: str) -> list[dict]:
    """Select the training rows of one arm.

    Args:
        arm: A key of ARMS.

    Returns:
        Train-split step rows of the arm.

    Raises:
        KeyError: If the arm is unknown.
    """
    if arm not in ARMS:
        raise KeyError(arm)
    rows = training_rows("train")
    real = [r for r in rows if r["dataset"] in REAL_STEP_SOURCES]
    proact = [r for r in rows if r["dataset"] == "atbench_steps"]
    generated = [r for r in rows if r["dataset"] == "gen_inject"]
    if arm == "A0":
        return real
    if arm == "A":
        return real + proact
    if arm == "B":
        return real + proact + generated
    if arm == "C":
        return real + proact + [r for r in generated if _branch(r) == "block"]
    return real + proact + [r for r in generated if attack_dataset(r) != "llmail_inject"]


# ---- evaluation sets -----------------------------------------------------------------------
def eval_sets() -> dict[str, dict]:
    """Assemble the evaluation sets of the three tiers.

    Returns:
        `{name: {"tier": 1 | 2 | 3, "rows": [...], "about": str}}`. Empty sets are left out.
    """
    test = training_rows("test")
    sets = {
        "injecagent_bxb": (1, [r for r in test if r["dataset"] == "injecagent"],
                           "InjecAgent grid B x B: unseen user tasks and unseen attacks"),
        "injecagent_bxb_hard_negatives": (1, [r for r in test if r["dataset"] == "injecagent" and r["decision"] == "ALLOW"],
                                          "Real agent outputs that ignored the injection (false positives under attack)"),
        "atbench_steps_test": (1, [r for r in test if r["dataset"] == "atbench_steps"],
                               "ATBench test runs unrolled by PROACT (second licensed maker)"),
        "redcode_heldout_categories": (1, [r for r in test if r["dataset"] == "redcode"],
                                       "RedCode risk categories never seen in training (shell / code execution)"),
        "benign_heldout": (1, [r for r in test if r["dataset"] in ("toucan", "toolace", "when2call") and r["decision"] == "ALLOW"],
                           "Held-out real benign traffic (over-defence)"),
        "diagnostic_generated": (3, list(training_rows("diagnostic")),
                                 "Generated from held-out seeds (synthetic; never a headline number)"),
    }
    for dataset in eval_only_datasets():
        rows = eval_only_rows(dataset)
        for origin in sorted({r["source"] for r in rows}):
            sets[f"tier2_{origin.replace('/', '_')}"] = (2, [r for r in rows if r["source"] == origin],
                                                        f"{origin}: internal transfer check (unlicensed, never trained on)")
    return {name: {"tier": tier, "rows": rows, "about": about} for name, (tier, rows, about) in sets.items() if rows}


def balance_weights(rows: list[dict]) -> list[float]:
    """Weights that give each source equal total weight and each class equal weight within a source.

    Args:
        rows: Training rows.

    Returns:
        One weight per row, clipped to [0.25, 4] per factor and normalised to mean 1.
    """
    by_source = Counter(r["source"] for r in rows)
    by_class = Counter((r["source"], label(r)) for r in rows)
    classes = Counter(s for s, _ in by_class)
    clip = lambda x: max(0.25, min(4.0, x))  # noqa: E731
    raw = [clip(len(rows) / (len(by_source) * by_source[r["source"]]))
           * clip(by_source[r["source"]] / (classes[r["source"]] * by_class[(r["source"], label(r))]))
           for r in rows]
    mean = sum(raw) / len(raw)
    return [w / mean for w in raw]
