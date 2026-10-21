"""Step-2 outputs: data/training/ (training rows per split) and data/jev/ (Jev-format splits)."""
import copy
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone

from ..common.io import dumps, swap_in
from ..common.paths import JEV, TRAINING
from . import backfill, confidence, coverage, dedup, derive, jev_format, leakage_audit, split, split_plan, weights
from .config import build_config, build_fingerprint, data_kind, source_key
from .load import load_processed

AUX_LABELS = ("attack_vector", "failure_modes", "action_relation", "hard_negative", "adversarial_locations", "outcome")

# Both folders are replaced whole on every build, so their READMEs are written by the build itself.
TRAINING_README = """# data/training/

Written by `ingest/build.py` (step 2); replaced whole on every build, so do not edit by hand.

Real, relabelled real (PROACT) and synthetic data combined and split, licensed datasets only:

| File | Holds |
| --- | --- |
| `train.jsonl`, `validation.jsonl`, `test.jsonl`, `holdout.jsonl`, `diagnostic.jsonl` | One flat row per record: identity (record_id, dataset, source, `data_kind`, split, head, group_ids), `input`, the record's decision, auxiliary labels, resolved label confidence and status, training weight, provenance, and a pointer to its Jev trace |
| `report.json` | Split counts by data kind, source and decision; leakage, near-duplicate and shortcut audits; followers (derived records and where their seeds put them); split-plan drift; coverage matrix; weights; confidence status |
| `manifest.json` | Build fingerprint, inputs (each processed dataset's checksum and versions), file checksums |

Synthetic records only ever land in `train` (or `diagnostic`, from held-out seeds); `test` holds real and relabelled real data.
"""

JEV_README = """# data/jev/

Written by `ingest/build.py` (step 2) in the same build as data/training/; replaced whole on every build.
The same splits in Jev's formats. `deliver` (python -m deliver) selects from here and sends to Jev.

| File | Holds | Sent to Jev? |
| --- | --- | --- |
| `<split>/events.jsonl` | Input events, `refractal.agent-trace.v1`, one per line; a record's planned action is its trace's last event | Yes |
| `<split>/findings.jsonl` | The expected finding per trace, `refractal.agent-trace-finding.v1` (decision, verdicts, data_classes, threat_categories, shell_impacts) | Yes |
| `<split>/index.jsonl` | Local link from each trace back to its record: record_id, dataset, data kind, the record's decision, weight, verdict confidences | **No** |
| `manifest.json` | Build fingerprint, schemas, Jev settings, per-split summary, file checksums | No |
"""


def to_row(rec: dict, split_name: str, weight: float, conf: dict, status: dict, trace: dict) -> dict:
    """Flatten one record into a training-view row.

    Args:
        rec: The record (after backfill).
        split_name: Its split.
        weight: Its training weight.
        conf: `{label: confidence}` from `confidence.resolve_record`.
        status: `{label: calibration status}`.
        trace: The record's Jev trace from `jev_format.to_trace`.

    Returns:
        A row with identity (record_id, dataset, source, data_kind, split, head, granularity, group_ids), the
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
        "data_kind": data_kind(rec),
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
        item: An expected finding from `jev_format.to_trace`.
        row: The training row it belongs to.

    Returns:
        The decision's confidence for source "decision", the adversarial_locations confidence for
        source "adversarial_location", or None if unresolved.
    """
    label = "decision" if item["source"] == "decision" else "adversarial_locations"
    return row["label_confidence"].get(label)


def _index_row(row: dict) -> dict:
    """The local index entry for one trace: what links it back to its record. Never sent to Jev.

    Args:
        row: A training-view row.

    Returns:
        trace id, record id, dataset, source, data kind, split, the record's own decision, its weight,
        and the confidence of each verdict (by event id).
    """
    return {"trace_id": row["jev"]["trace_id"], "record_id": row["record_id"], "dataset": row["dataset"],
            "source": row["source"], "data_kind": row["data_kind"], "split": row["split"],
            "decision": row["decision"], "weight": row["weight"],
            "verdict_confidence": {x.get("event_id") or x.get("trace_id"): _expected_conf(x, row) for x in row["jev"]["expected"]}}


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
    data/jev/: per split, exactly what Jev reads and returns plus a local index:
    <split>/events.jsonl (`refractal.agent-trace.v1` events, one per line), <split>/findings.jsonl
    (the expected `refractal.agent-trace-finding.v1` finding per trace) and <split>/index.jsonl (trace
    id -> record id, dataset, data kind, weight and verdict confidences; never sent to Jev), manifest.json.

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
    followers = split.follower_report(records, splits)
    records = [r for r in records if splits[r["record_id"]] != split.EXCLUDED]
    resolved = {r["record_id"]: confidence.resolve_record(r) for r in records}
    decision_conf = {rid: c.get("decision") or 1.0 for rid, (c, _) in resolved.items()}
    weight = weights.compute(records, splits, decision_conf)
    traces = {r["record_id"]: jev_format.to_trace(r) for r in records}

    rows_by_split = {name: [] for name in split.SPLITS}
    # Ordered by the opaque trace id, not record_id: record ids group rows by dataset and source file
    # (e.g. "...:DPI_attack_success:..."), and that order would reach a replay that reads traces in sequence.
    for rec in sorted(records, key=lambda r: traces[r["record_id"]]["trace_id"]):
        rid = rec["record_id"]
        conf, status = resolved[rid]
        rows_by_split[splits[rid]].append(to_row(rec, splits[rid], weight[rid], conf, status, traces[rid]))
    audit_report = leakage_audit.run(records, splits, {name: [e for r in rows for e in traces[r["record_id"]]["events"]]
                                               for name, rows in rows_by_split.items()})

    findings = {rid: jev_format.to_finding(rec, traces[rid]) for rec in records for rid in [rec["record_id"]]}
    train_dir, jev_dir = _staging(TRAINING), _staging(JEV)
    train_files, jev_files = {}, {}
    for name, rows in rows_by_split.items():
        train_files[f"{name}.jsonl"] = _write_lines(train_dir / f"{name}.jsonl", [dumps(r) for r in rows])
        (jev_dir / name).mkdir()
        jev_files[f"{name}/events.jsonl"] = _write_lines(
            jev_dir / name / "events.jsonl", [dumps(e) for r in rows for e in traces[r["record_id"]]["events"]])
        jev_files[f"{name}/findings.jsonl"] = _write_lines(
            jev_dir / name / "findings.jsonl", [dumps(findings[r["record_id"]]) for r in rows if findings[r["record_id"]]])
        jev_files[f"{name}/index.jsonl"] = _write_lines(jev_dir / name / "index.jsonl", [dumps(_index_row(r)) for r in rows])

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
        "followers": followers,
        "split_plan": split_plan.drift(records, splits),
        "coverage": coverage.report(records, splits),
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
    (train_dir / "README.md").write_text(TRAINING_README, encoding="utf-8")
    (jev_dir / "README.md").write_text(JEV_README, encoding="utf-8")
    (train_dir / "manifest.json").write_text(json.dumps({**common, "files": train_files}, indent=2), encoding="utf-8")
    (jev_dir / "manifest.json").write_text(json.dumps({
        **common,
        "input_schema": build_config()["jev"]["input_schema"],
        "finding_schema": jev_format.FINDING_SCHEMA,
        "expected_decisions": "allow | block (Jev vocabulary)",
        "review_as": build_config()["jev"]["review_as"],
        "label_tool_results": build_config()["jev"]["label_tool_results"],
        "summary": jev_summary,
        "files": jev_files,
    }, indent=2), encoding="utf-8")
    swap_in(train_dir, TRAINING)
    swap_in(jev_dir, JEV)
    return report


def plan_splits(datasets: list[str]) -> dict:
    """Write the real-data split plan (`ingest/build.py --plan-splits`).

    Runs the same load, backfill, deduplication and split as `build` on the real (non-derived)
    datasets only, and writes every record's split to the plan file. Nothing else is written.

    Args:
        datasets: Processed datasets the licence gate admits; derived ones are skipped.

    Returns:
        The plan summary from `split_plan.write_plan`.

    Raises:
        load.BuildInputError: If the processed inputs are stale, inconsistent or tampered with.
    """
    real = [d for d in datasets if build_config()["sources"].get(d, {}).get("role") != "derived"]
    records, _ = load_processed(real)
    records = copy.deepcopy(records)
    backfill.backfill(records)
    records, _ = dedup.deduplicate(records)
    return split_plan.write_plan(records, split.assign_all(records))
