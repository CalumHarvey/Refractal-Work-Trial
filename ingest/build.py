"""Step 2: build the training view (data/training/) and the Jev-format splits (data/jev/).

Usage, from any directory:
    .venv/Scripts/python ingest/build.py             # build from every processed dataset
    .venv/Scripts/python ingest/build.py --status    # are data/training/ and data/jev/ up to date?
Output: data/training/{train,validation,test,holdout}.jsonl + report.json + manifest.json, and
data/jev/<split>/{events.jsonl, expected.jsonl} + manifest.json (Jev replay input and expected findings).
Roles, split ratios, weighting and the licence gate (config `licences`: which processed datasets
may enter the build) live in config/build.yaml.
"""
import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, "") and "__file__" in globals():
    # Run as a plain script: put the project root on the path so the `ingest` package imports.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.assembly.config import build_fingerprint, licensed_datasets  # noqa: E402
from ingest.assembly.export import build  # noqa: E402
from ingest.assembly.load import BuildInputError  # noqa: E402
from ingest.common.paths import JEV, PROCESSED, TRAINING  # noqa: E402
from ingest.run import available_datasets  # noqa: E402


def status() -> dict:
    """Report whether data/training/ and data/jev/ match the current processed data, config and code.

    Prints one line.

    Returns:
        `{"state": "current" | "stale" | "missing", "differs": [what changed]}`.
    """
    path = TRAINING / "manifest.json"
    if not path.exists():
        result = {"state": "missing", "differs": []}
    else:
        made = json.loads(path.read_text(encoding="utf-8"))
        differs = []
        if made.get("build_fingerprint") != build_fingerprint():
            differs.append("config, mappings or code")
        jev_manifest = JEV / "manifest.json"
        if not jev_manifest.exists() or json.loads(jev_manifest.read_text(encoding="utf-8")).get(
                "build_fingerprint") != made.get("build_fingerprint"):
            differs.append("data/jev out of step with data/training")
        for dataset in licensed_datasets(available_datasets())[0]:
            m = PROCESSED / dataset / "manifest.json"
            current = json.loads(m.read_text(encoding="utf-8"))["records_sha256"] if m.exists() else None
            if (made.get("inputs", {}).get(dataset) or {}).get("records_sha256") != current:
                differs.append(f"processed {dataset}")
        result = {"state": "stale" if differs else "current", "differs": differs}
    detail = f" ({'; '.join(result['differs'])} changed)" if result["differs"] else ""
    print(f"training view + jev splits: {result['state']}{detail}")
    return result


def main(argv=None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments to parse; None uses sys.argv. `--status` only reports whether the training
            view is up to date.

    Returns:
        Exit code: 0 on a successful build (or a current status), 1 if the inputs are not buildable
        (or the view is stale / missing).
    """
    parser = argparse.ArgumentParser(description="Build the training view from the processed datasets.")
    parser.add_argument("--status", action="store_true", help="report whether data/training/ is up to date")
    args = parser.parse_args(argv)
    if args.status:
        return 0 if status()["state"] == "current" else 1
    included, excluded = licensed_datasets(available_datasets())
    for dataset, reason in excluded.items():
        print(f"left out: {dataset} ({reason})", file=sys.stderr)
    try:
        report = build(included, excluded)
    except BuildInputError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(json.dumps({name: counts["total"] for name, counts in report["splits"].items()}))
    for warning in report["audit"]["warnings"]:
        print(f"audit: {warning}", file=sys.stderr)
    leak = report["leakage"]["enforced_keys_in_several_splits"]
    if leak:
        print(f"ATTENTION: {leak} group keys span several splits", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
