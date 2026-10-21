"""Coverage matrix: records per taxonomy cell, per split. Generation targets the thin cells.

A cell is failure mode x attack vector (entry channel) x decision x action surface x context
available. Modes are counted once per record per mode; records without modes count as "none"
(verified empty) or "unknown" (null).
"""
from collections import Counter, defaultdict

from .derive import action_surface, context_available


def cells(rec: dict) -> list[str]:
    """Name the coverage cells a record falls in.

    Args:
        rec: A record.

    Returns:
        One "mode|attack_vector|decision|surface|context" string per failure mode of the record.
    """
    labels = rec["labels"]
    modes = labels["failure_modes"]
    names = ["unknown"] if modes is None else ["none"] if not modes else [str(m) for m in modes]
    rest = f'{labels["attack_vector"]}|{labels["decision"]}|{action_surface(rec)}|{context_available(rec)}'
    return [f"{m}|{rest}" for m in names]


def report(records: list[dict], splits: dict[str, str]) -> dict:
    """Count step and trajectory records per coverage cell, per split.

    Args:
        records: All exported records.
        splits: `{record_id: split}`.

    Returns:
        `{"cell_format": ..., "by_split": {split: {cell: n}}, "modes_by_decision": {split: {mode: {decision: n}}}}`.
    """
    by_split = defaultdict(Counter)
    modes = defaultdict(lambda: defaultdict(Counter))
    for rec in records:
        if rec["granularity"] not in ("step", "trajectory"):
            continue
        name = splits[rec["record_id"]]
        for cell in cells(rec):
            by_split[name][cell] += 1
            modes[name][cell.split("|")[0]][rec["labels"]["decision"]] += 1
    return {"cell_format": "failure_mode|attack_vector|decision|action_surface|context_available",
            "by_split": {k: dict(sorted(v.items())) for k, v in by_split.items()},
            "modes_by_decision": {k: {m: dict(d) for m, d in sorted(v.items())} for k, v in modes.items()}}
