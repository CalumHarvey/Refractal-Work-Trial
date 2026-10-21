"""Convert raw datasets into processed AgentDecisionRecords.

Usage, from any directory (paths are resolved from this file, not the working directory):
    .venv/Scripts/python ingest/run.py                # every dataset that has a converter
    .venv/Scripts/python ingest/run.py atbench        # one dataset
    .venv/Scripts/python -m ingest.run atbench        # or as a module, from the project root
    .venv/Scripts/python ingest/run.py --status       # which processed datasets are out of date
Output: data/processed/<dataset>/{records.jsonl, rejects.jsonl, report.json, samples/, manifest.json},
replaced atomically by each run; the versions that produced it are in manifest.json.
"""
import argparse
import importlib
import json
import pkgutil
import sys
from collections import Counter
from pathlib import Path

if __package__ in (None, "") and "__file__" in globals():
    # Run as a plain script: put the project root on the path so the `ingest` package imports.
    # (Interactive sessions and notebooks define no __file__; there the project root must already be
    # importable, e.g. by starting them in the project folder.)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.common import record as record_mod  # noqa: E402
from ingest.common.io import Output  # noqa: E402
from ingest.common.manifest import processed_state  # noqa: E402
from ingest.common.paths import mappings_version, raw_snapshot  # noqa: E402
from ingest.common.validate import problems  # noqa: E402
import ingest.convert  # noqa: E402

# Order matters only for readability of the output: simplest first, LLMail-Inject (largest) last.
PREFERRED_ORDER = ("atbench", "r_judge", "toolsafe", "llmail_inject")


def available_datasets() -> list[str]:
    """List the datasets that have a converter.

    Every module in ingest/convert/ is a converter, so new ones are picked up automatically.

    Returns:
        Dataset names, in PREFERRED_ORDER first, then alphabetically.
    """
    found = [m.name for m in pkgutil.iter_modules(ingest.convert.__path__) if not m.name.startswith("_")]
    return sorted(found, key=lambda d: (PREFERRED_ORDER.index(d) if d in PREFERRED_ORDER else len(PREFERRED_ORDER), d))


def rules_fired(rec: dict) -> list[str]:
    """List the rules that set labels on a record, for choosing samples.

    Args:
        rec: A built record.

    Returns:
        Sorted rule ids from its provenance, plus a "needs_backfill.<label>" pseudo-id per
        flagged label.
    """
    prov = rec["provenance"]
    rules = {p["rule"] for k, p in prov.items() if k != "failure_modes"}
    rules |= {e["rule"] for e in prov.get("failure_modes", [])}
    rules |= {f"needs_backfill.{label}" for label in rec["needs_backfill"]}
    return sorted(rules)


def summary(records: list[dict]) -> dict:
    """Summarise label values across records for report.json.

    Args:
        records: The valid converted records.

    Returns:
        Counts by granularity, decision, attack_vector, failure mode, failure-mode state
        (null / empty / set), hard_negative, backfill flag and provenance origin.
    """
    C = Counter
    lab = lambda name: [r["labels"][name] for r in records]  # noqa: E731
    return {
        "granularity": dict(C(r["granularity"] for r in records)),
        "decision": dict(C(map(str, lab("decision")))),
        "attack_vector": dict(C(map(str, lab("attack_vector")))),
        "failure_modes": dict(C(str(m) for ms in lab("failure_modes") if ms for m in ms)),
        "failure_modes_state": {"null": sum(m is None for m in lab("failure_modes")),
                                "empty": sum(m == [] for m in lab("failure_modes")),
                                "set": sum(bool(m) for m in lab("failure_modes"))},
        "hard_negative": dict(C(map(str, lab("hard_negative")))),
        "needs_backfill": dict(C(label for r in records for label in r["needs_backfill"])),
        "origins": dict(C(p["origin"] for r in records for k, p in r["provenance"].items() if k != "failure_modes")
                        + C(e["origin"] for r in records for e in r["provenance"].get("failure_modes", []))),
    }


def run(dataset: str) -> dict:
    """Convert one dataset end to end.

    Checks rule ids against the YAML, converts and validates every raw item (failures become
    rejects, never silent drops) and writes the processed folder.

    Args:
        dataset: Dataset name, e.g. "atbench".

    Returns:
        The run report, also written to report.json.

    Raises:
        SystemExit: If the converter's rule ids are out of sync with the mappings YAML.
    """
    conv = importlib.import_module(f"ingest.convert.{dataset}")
    if conv.RULES.missing_from_code() or conv.RULES.missing_from_yaml():
        raise SystemExit(f"rule ids out of sync with the mappings: code missing {conv.RULES.missing_from_code()}, "
                         f"yaml missing {conv.RULES.missing_from_yaml()}")
    record_mod.CONVERTER_RULE_HITS.clear()
    conv.RULES.hits.clear()

    snapshot = raw_snapshot(dataset)
    raw_manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    out = Output(dataset)
    n_in = 0
    for original_id, src in conv.iter_source(snapshot):
        n_in += 1
        try:
            record_id, rec = conv.to_record(original_id, src, raw_manifest["revision"])
            built = rec.build(record_id)
        except Exception as exc:  # any conversion failure becomes a reject, never a silent drop
            out.reject(original_id, [f"conversion: {type(exc).__name__}: {exc}"])
            continue
        issues = problems(built)
        if issues:
            out.reject(original_id, issues)
        else:
            out.add(built, rules_fired(built))

    report = {
        "dataset": dataset,
        "mappings_version": mappings_version(),
        "raw_revision": raw_manifest["revision"],
        "input_records": n_in,
        "output_records": len(out.records),
        "rejects": len(out.rejects),
        "reject_reasons": dict(Counter(r.split(":")[0] + ": " + r.split(":")[1].strip()[:80]
                                       for rej in out.rejects for r in rej["reasons"])),
        "rule_hits": dict(conv.RULES.hits),
        "converter_rule_hits": dict(record_mod.CONVERTER_RULE_HITS),
        "labels": summary(out.records),
        "dataset_checks": conv.report_extras(out.records),
    }
    out.write(report, raw_manifest)
    return report


def problems_in(report: dict) -> list[str]:
    """List the problems a run report shows.

    Args:
        report: A report from `run`.

    Returns:
        Readable problems (rejects, failed reconciliation checks); empty if the run was clean.
    """
    recon = report["dataset_checks"].get("reconciliation", {})
    failed = [k for k, v in recon.items() if not v["ok"]]
    out = []
    if report["rejects"]:
        out.append(f"{report['rejects']} rejects")
    if failed:
        out.append(f"reconciliation failures: {failed}")
    return out


def run_one(dataset: str) -> bool:
    """Convert one dataset and print its summary line.

    Args:
        dataset: Dataset name.

    Returns:
        True if the run had no rejects and every reconciliation check passed.
    """
    report = run(dataset)
    print(json.dumps({k: report[k] for k in ("dataset", "input_records", "output_records", "rejects")}))
    issues = problems_in(report)
    if issues:
        print(f"ATTENTION {dataset}: {'; '.join(issues)}", file=sys.stderr)
    return not issues


def run_all() -> dict[str, str]:
    """Convert every dataset that has a converter.

    A dataset that fails or has issues is reported, and the others still run.

    Returns:
        `{dataset: status}`, where status is "ok", "issues" or "error: <message>".
    """
    results = {}
    for dataset in available_datasets():
        try:
            results[dataset] = "ok" if run_one(dataset) else "issues"
        except Exception as exc:  # report and carry on with the next dataset
            results[dataset] = f"error: {type(exc).__name__}: {exc}"
            print(f"ERROR {dataset}: {type(exc).__name__}: {exc}", file=sys.stderr)
    print(json.dumps({"run_all": results}))
    return results


def status() -> dict[str, dict]:
    """Compare each dataset's processed output with what the current code and spec would produce.

    An output is stale if any of these differ from now: mappings version, schema version, code
    fingerprint of ingest/, or the raw snapshot's revision. Prints one line per dataset.

    Returns:
        `{dataset: {"state": "current" | "stale" | "missing", "differs": [what changed], ...}}`,
        where the extra keys are the processed manifest's versions, fingerprint and record count.
    """
    results = {}
    for dataset in available_datasets():
        state = processed_state(dataset)
        made = state.pop("manifest") or {}
        results[dataset] = {**state, **{k: made.get(k) for k in ("mappings_version", "schema_version",
                                                                 "code_fingerprint", "records", "created_at")}}
        r = results[dataset]
        detail = f" ({', '.join(r['differs'])} changed)" if r["differs"] else ""
        made_with = f" mappings {r.get('mappings_version')}, {r.get('records')} records, {r.get('created_at')}" \
            if r["state"] != "missing" else ""
        print(f"{dataset:<15} {r['state']}{detail}{made_with}")
    return results


def main(argv=None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments to parse; None uses sys.argv. One optional positional argument names a
            dataset; without it, every dataset is converted. `--status` only reports which processed
            datasets are out of date, converting nothing.

    Returns:
        Exit code: 0 if every converted dataset was clean (or, with --status, every dataset is
        current), otherwise 1.
    """
    # A literal, not __doc__: docstrings are None under `python -OO` and in interactive/notebook runs.
    parser = argparse.ArgumentParser(description="Convert raw datasets into processed AgentDecisionRecords.")
    parser.add_argument("dataset", nargs="?", choices=available_datasets(),
                        help="dataset to convert; omit to convert all of them")
    parser.add_argument("--status", action="store_true",
                        help="report which processed datasets are missing or out of date, and convert nothing")
    args = parser.parse_args(argv)
    if args.status:
        return 0 if all(r["state"] == "current" for r in status().values()) else 1
    if args.dataset:
        return 0 if run_one(args.dataset) else 1
    return 0 if all(v == "ok" for v in run_all().values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
