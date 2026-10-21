"""Run folders with a manifest: data/generated/<dataset>/<run>/ for synthetic data (content a model
wrote) and data/derived/<dataset>/<run>/ for relabelled real data (real content, located labels).

A run is written in place while it is being produced (so an interrupted run resumes), and its
manifest is rewritten at the end of every invocation. The manifest's `revision` is the run id plus a
hash of the run's main file, so a converted output goes stale (ingest/run.py --status) whenever the
run's content changes.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ingest.common.io import dumps, read_jsonl  # noqa: F401  (re-exported for the generate modules)
from ingest.assembly.config import data_kind_of_source
from ingest.common.paths import DERIVED, GENERATED, ROOT


def run_dir(dataset: str, run: str) -> Path:
    """Locate (and create) a run folder, under the root its data kind belongs in.

    Args:
        dataset: Dataset name, e.g. "gen_inject" (synthetic) or "atbench_steps" (relabelled real).
        run: Run id, e.g. "inject-pilot".

    Returns:
        data/derived/<dataset>/<run>/ for relabelled real data, else data/generated/<dataset>/<run>/;
        created if missing.
    """
    root = DERIVED if data_kind_of_source(dataset) == "relabelled_real" else GENERATED
    path = root / dataset / run
    path.mkdir(parents=True, exist_ok=True)
    return path


def append_jsonl(path: Path, rows: list[dict]) -> None:
    """Append rows to a JSONL file as canonical JSON.

    Args:
        path: The file.
        rows: Rows to append.

    Returns:
        None.
    """
    with open(path, "a", encoding="utf-8") as f:
        for row in rows:
            f.write(dumps(row) + "\n")


def write_jsonl(path: Path, rows: list[dict]) -> str:
    """Write rows to a JSONL file as canonical JSON, replacing it.

    Args:
        path: The file.
        rows: Rows to write.

    Returns:
        SHA-256 of the written bytes.
    """
    data = "".join(dumps(r) + "\n" for r in rows).encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> str | None:
    """Hash a file.

    Args:
        path: The file.

    Returns:
        SHA-256 hex digest, or None if it does not exist.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def write_manifest(folder: Path, dataset: str, run: str, main_file: str, extra: dict) -> dict:
    """Write a run's manifest.

    Args:
        folder: The run folder.
        dataset: Generated dataset name (what `raw_snapshot` matches).
        run: Run id.
        main_file: The file the converter reads; its hash goes into `revision`.
        extra: Further fields (parents, models, prompt versions, counts...).

    Returns:
        The manifest written.
    """
    files = {p.name: file_sha(p) for p in sorted(folder.iterdir()) if p.is_file() and p.name != "manifest.json"}
    manifest = {"dataset": dataset, "run": run, "source": f"generate ({dataset}, run {run})",
                "revision": f"{run}:{(files.get(main_file) or 'empty')[:16]}",
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "folder": folder.relative_to(ROOT).as_posix(), "files": files, **extra}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest
