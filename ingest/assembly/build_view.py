"""Step-2 outputs: data/training/ (training rows per split) and data/jev/ (Jev-format splits)."""
import copy
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone

from ..common.io import dumps, swap_in
from ..common.paths import JEV, TRAINING
from . import audit, backfill, confidence, dedup, derive, jev, split, weights
from .config import build_config, build_fingerprint, source_key
from .load import load_processed

AUX_LABELS = ("attack_vector", "failure_modes", "action_relation", "hard_negative", "adversarial_locations", "outcome")


def to_row(rec: dict, split_name: str, weight: float, conf: dict, status: dict, trace: dict) -> dict:
    """Flatten one record into a training-view row.

    Args:
        rec: The record (after backfill).
        split_name: Its split.
        weight: Its training weight.
        conf: `{label: confidence}` from `confidence.resolve_record`.
        status: `{label: calibration status}`.
        trace: The record's Jev trace from `jev.to_trace`.

    Returns:
        A row with identity (record_id, dataset, source, split, head, granularity, group_ids), the
        structured `input`, a pointer into data/jev/ (`jev`: trace id, target event id, expected
        findings; the events themselves are only in data/jev/), the
        record's own three-way `decision`, auxiliary labels (plus derived is_attack and effects),
        per-label confidence and status, the weight, remaining backfill flags and the provenance
        (for tracing a label back to its rule).
    """
    return {
        "record_id": rec["record_id"],
        "dataset": rec["source"]["dataset"],
        "source": source_key(rec),
        "split": split_name,
        "head": weights.head(rec),
        "granularity": rec["granularity"],
        "group_ids": rec["source"]["group_ids"],
        "input": rec["input"],
        "jev": {"trace_id": trace["trace_id"], "target_event_id": trace["target_event_id"],
                "expected": trace["expected"]},
        "decision": rec["labels"]["decision"],
        "aux": {**{k: rec["labels"][k] for k in AUX_LABELS},
                "is_attack": derive.is_attack(rec), "effects": derive.effects(rec)},
        "label_confidence": conf,
        "label_status": status,
        "weight": weight,
        "needs_backfill": rec["needs_backfill"],
        "provenance": rec["provenance"],
    }


def _expected_conf(item: dict, row: dict) -> float | None:
    """Confidence of an expected finding, from the label it was derived from.

    Args:
        item: An expected finding from `jev.to_trace`.
        row: The training row it belongs to.

    Returns:
        The decision's confidence for source "decision", the adversarial_locations confidence for
        source "adversarial_location", or None if unresolved.
    """
    label = "decision" if item["source"] == "decision" else "adversarial_locations"
    return row["label_confidence"].get(label)


def _write_lines(path, lines: list[str]) -> dict:
    """Write lines to a file and describe it for the manifest.

    Args:
        path: Destination file.
        lines: Lines to write, without newlines.

    Returns:
        `{"rows": n, "sha256": hex}`.
    """
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for line in lines:
            f.write(line + "\n")
    return {"rows": len(lines), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _staging(final):
    """Create an empty staging folder next to an output folder.

    Args:
        final: The output folder (data/training or data/jev).

    Returns:
        `<final>.tmp`, emptied and created.
    """
    staging = final.with_name(final.name + ".tmp")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    return staging


def build(datasets: list[str], left_out: dict[str, str] | None = None) -> dict:
    """Run step 2 end to end and write data/training/ and data/jev/.

    Stages: load and verify -> backfill (rules only) -> deduplicate -> assign splits -> resolve
    confidence -> weights -> Jev traces -> leakage / shortcut audit -> export. Rows within a split
    are ordered by trace id. Both folders are written to `.tmp` staging folders
    and swapped in only when complete.

    data/training/: <split>.jsonl (training rows), report.json, manifest.json.
    data/jev/: <split>/events.jsonl (`refractal.agent-trace.v1` events, one per line, ready for
    Jev's replay) and <split>/expected.jsonl (expected findings with record_id, weight and
    confidence), manifest.json.

    Args:
        datasets: Processed datasets to include.
        left_out: `{dataset: reason}` for processed datasets the licence gate excluded, recorded
            in the report.

    Returns:
        The build report (also written to data/training/report.json).

    Raises:
        load.BuildInputError: If the processed inputs are stale, inconsistent or tampered with.
    """
    records, manifests = load_processed(datasets)
    records = copy.deepcopy(records)
    n_loaded = len(records)
    backfill_stats = backfill.backfill(records)
    records, dedup_stats = dedup.deduplicate(records)
    splits = split.assign_all(records)
    resolved = {r["record_id"]: confidence.resolve_record(r) for r in records}
    decision_conf = {rid: c.get("decision") or 1.0 for rid, (c, _) in resolved.items()}
    weight = weights.compute(records, splits, decision_conf)
    traces = {r["record_id"]: jev.to_trace(r) for r in records}

    rows_by_split = {name: [] for name in split.SPLITS}
    # Ordered by the opaque trace id, not record_id: record ids group rows by dataset and source file
    # (e.g. "...:DPI_attack_success:..."), and that order would reach a replay that reads traces in sequence.
    for rec in sorted(records, key=lambda r: traces[r["record_id"]]["trace_id"]):
        rid = rec["record_id"]
        conf, status = resolved[rid]
        rows_by_split[splits[rid]].append(to_row(rec, splits[rid], weight[rid], conf, status, traces[rid]))
    audit_report = audit.run(records, splits, {name: [e for r in rows for e in traces[r["record_id"]]["events"]]
                                               for name, rows in rows_by_split.items()})

    train_dir, jev_dir = _staging(TRAINING), _staging(JEV)
    train_files, jev_files = {}, {}
    for name, rows in rows_by_split.items():
        train_files[f"{name}.jsonl"] = _write_lines(train_dir / f"{name}.jsonl", [dumps(r) for r in rows])
        (jev_dir / name).mkdir()
        jev_files[f"{name}/events.jsonl"] = _write_lines(
            jev_dir / name / "events.jsonl", [dumps(e) for r in rows for e in traces[r["record_id"]]["events"]])
        jev_files[f"{name}/expected.jsonl"] = _write_lines(
            jev_dir / name / "expected.jsonl",
            [dumps({**x, "record_id": r["record_id"], "weight": r["weight"], "confidence": _expected_conf(x, r)})
             for r in rows for x in r["jev"]["expected"]])

    jev_summary = {name: {"traces": len(rows),
                          "events": sum(len(traces[r["record_id"]]["events"]) for r in rows),
                          "expected_by_source_and_decision": dict(Counter(
                              f'{x["source"]}:{x["decision"]}' for r in rows for x in r["jev"]["expected"])),
                          "review_records": sum(r["decision"] == "REVIEW" for r in rows)}
                   for name, rows in rows_by_split.items()}
    report = {
        "loaded": {"datasets": datasets, "records": n_loaded, "left_out": left_out or {}},
        "backfill": backfill_stats,
        "dedup": dedup_stats,
        "splits": split.split_counts(records, splits),
        "leakage": split.leakage(records, splits),
        "forced_to_holdout": split.forced_to_holdout(records, splits),
        "weights": weights.summary(records, splits, weight),
        "confidence": {
            "decision_status": dict(Counter(s.get("decision") for _, s in resolved.values())),
            "decision_confidence": dict(Counter(str(c.get("decision")) for c, _ in resolved.values())),
        },
        "jev": jev_summary,
        "audit": audit_report,
        "slices": {name: {"hard_negatives": sum(r["aux"]["hard_negative"] is True for r in rows),
                          "attack_vector": dict(Counter(str(r["aux"]["attack_vector"]) for r in rows)),
                          "needs_backfill": sum(bool(r["needs_backfill"]) for r in rows),
                          "head": dict(Counter(str(r["head"]) for r in rows))}
                   for name, rows in rows_by_split.items()},
    }
    common = {
        "build_version": build_config()["build_version"],
        "build_fingerprint": build_fingerprint(),
        "inputs": {d: {k: m[k] for k in ("records_sha256", "mappings_version", "schema_version", "code_fingerprint",
                                         "raw_revision")} for d, m in manifests.items()},
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (train_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    (train_dir / "manifest.json").write_text(json.dumps({**common, "files": train_files}, indent=2), encoding="utf-8")
    (jev_dir / "manifest.json").write_text(json.dumps({
        **common,
        "input_schema": build_config()["jev"]["input_schema"],
        "expected_decisions": "allow | block (Jev vocabulary)",
        "review_as": build_config()["jev"]["review_as"],
        "label_tool_results": build_config()["jev"]["label_tool_results"],
        "summary": jev_summary,
        "files": jev_files,
    }, indent=2), encoding="utf-8")
    swap_in(train_dir, TRAINING)
    swap_in(jev_dir, JEV)
    return report
