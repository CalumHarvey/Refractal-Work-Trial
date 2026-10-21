"""The real-data split plan: every real record's split, frozen before generation.

`ingest/build.py --plan-splits` writes it; the generate package reads it so that only train-side
records and keys become seeds. Followers never depend on it for safety (they take their seeds'
actual split at build time); the plan only decides which seeds generation may use. Each build
reports how far the real records' splits have drifted from the plan.
"""
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from ..common.paths import ROOT
from .config import build_config, build_fingerprint, is_derived


def plan_path() -> Path:
    """Locate the split plan file.

    Returns:
        The path in config `split_plan`, relative to the project root.
    """
    return ROOT / build_config()["split_plan"]


def write_plan(records: list[dict], splits: dict[str, str]) -> dict:
    """Write the split of every real (non-derived) record.

    Args:
        records: The deduplicated records of the build.
        splits: `{record_id: split}` from `split.assign_all`.

    Returns:
        A summary: path, number of records and counts per split.
    """
    real = {r["record_id"]: splits[r["record_id"]] for r in records if not is_derived(r)}
    path = plan_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "build_fingerprint": build_fingerprint(), "splits": dict(sorted(real.items()))}
    path.write_text(json.dumps(payload, indent=0, sort_keys=True), encoding="utf-8")
    return {"path": str(path.relative_to(ROOT)), "records": len(real), "by_split": dict(Counter(real.values()))}


def load_plan() -> dict[str, str]:
    """Read the split plan.

    Returns:
        `{record_id: split}`.

    Raises:
        FileNotFoundError: If no plan has been written (run `ingest/build.py --plan-splits`).
    """
    path = plan_path()
    if not path.exists():
        raise FileNotFoundError(f"no split plan at {path}; run ingest/build.py --plan-splits")
    return json.loads(path.read_text(encoding="utf-8"))["splits"]


def drift(records: list[dict], splits: dict[str, str]) -> dict:
    """Compare the real records' splits in this build with the plan.

    Args:
        records: The deduplicated records of the build.
        splits: `{record_id: split}` from `split.assign_all`.

    Returns:
        `{"plan": "present" | "missing", "real_records", "not_in_plan", "moved"}`. Moved records mean
        seeds chosen from the plan may now sit in another split; their generated records follow them
        there (so nothing leaks), but generation should be re-planned.
    """
    try:
        plan = load_plan()
    except FileNotFoundError:
        return {"plan": "missing"}
    real = [r["record_id"] for r in records if not is_derived(r)]
    return {"plan": "present", "real_records": len(real),
            "not_in_plan": sum(rid not in plan for rid in real),
            "moved": sum(rid in plan and plan[rid] != splits[rid] for rid in real)}
