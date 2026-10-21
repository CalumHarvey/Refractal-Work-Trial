"""Package selected traces for Jev: each item is a trace's events plus its expected finding.

Only Jev's own formats leave the machine: events (`refractal.agent-trace.v1`) and the expected
finding (`refractal.agent-trace-finding.v1`). Record ids, dataset names, data kinds, weights and
confidences stay in the local index.
"""
from collections import defaultdict

from ingest.common.io import read_jsonl
from ingest.common.paths import JEV


def _read_by_trace(path) -> dict[str, list[dict]]:
    """Group a JSONL file's rows by trace id.

    Args:
        path: An events.jsonl or findings.jsonl file.

    Returns:
        `{trace_id: [rows in file order]}`.
    """
    grouped = defaultdict(list)
    for row in read_jsonl(path):
        grouped[row["trace_id"]].append(row)
    return grouped


def items(split: str, trace_ids: list[str]) -> list[dict]:
    """Build the delivery items of one split, in the given order.

    Args:
        split: Split name.
        trace_ids: Selected traces.

    Returns:
        `{"trace_id", "events": [...], "expected_finding": finding | None}` per trace.

    Raises:
        ValueError: If a selected trace has no events (data/jev is inconsistent).
    """
    events = _read_by_trace(JEV / split / "events.jsonl")
    findings = _read_by_trace(JEV / split / "findings.jsonl")
    out = []
    for tid in trace_ids:
        if not events.get(tid):
            raise ValueError(f"trace {tid} has no events in data/jev/{split}")
        out.append({"trace_id": tid, "events": events[tid], "expected_finding": (findings.get(tid) or [None])[0]})
    return out


def batches(rows: list[dict], size: int) -> list[list[dict]]:
    """Cut items into batches.

    Args:
        rows: Delivery items.
        size: Items per batch.

    Returns:
        Consecutive batches of at most `size` items.
    """
    return [rows[i:i + size] for i in range(0, len(rows), size)]


def request_body(split: str, batch: list[dict]) -> dict:
    """The body of one ingestion request (placeholder shape until Jev's API is defined).

    Args:
        split: The split the traces belong to (train / validation / test ...).
        batch: Delivery items.

    Returns:
        `{"split", "traces": [{"trace_id", "events", "expected_finding"}]}`.
    """
    return {"split": split, "traces": batch}
