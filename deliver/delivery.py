"""One delivery run: check data/jev is current, select, package, send, and record what was sent.

Output: data/delivery/<run>/ with `<split>/batch-0001.json ...` (the exact request bodies),
`<split>/responses.jsonl` (one reply per batch), `selected_index.jsonl` (the local index of what was
sent, for joining Jev's results back to records) and `manifest.json` (selection, counts, endpoint,
dry-run flag, the build it came from).
"""
import json
from datetime import datetime, timezone

from ingest.assembly.config import build_fingerprint
from ingest.common.io import dumps
from ingest.common.paths import JEV, ROOT

from . import package
from .client import JevClient
from .selection import Selection, deliver_config, select, summary


class StaleBuild(RuntimeError):
    """Raised when data/jev does not match the current config, mappings and code."""


def check_current() -> dict:
    """Make sure data/jev comes from the current build.

    Returns:
        The data/jev manifest.

    Raises:
        StaleBuild: If data/jev is missing or was built from other config, mappings or code.
    """
    path = JEV / "manifest.json"
    if not path.exists():
        raise StaleBuild("data/jev is missing; run ingest/build.py")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("build_fingerprint") != build_fingerprint():
        raise StaleBuild("data/jev is stale (config, mappings or code changed); run ingest/build.py")
    return manifest


def run(run_id: str | None = None, selection: Selection | None = None, dry_run: bool | None = None) -> dict:
    """Deliver the selected traces to Jev (or write the requests only, when dry-running).

    Args:
        run_id: Name of the delivery folder; defaults to a UTC timestamp.
        selection: What to send; defaults to config `selection`.
        dry_run: Override for config `api.dry_run`.

    Returns:
        The manifest written to the delivery folder.

    Raises:
        StaleBuild: If data/jev is not current.
        client.JevError: If Jev rejects a request (the batches sent so far are recorded).
    """
    jev_manifest = check_current()
    cfg = deliver_config()
    selection = selection or Selection.from_config()
    client = JevClient(cfg["api"], dry_run)
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    folder = ROOT / cfg["output_dir"] / run_id
    folder.mkdir(parents=True, exist_ok=True)
    selected = select(selection)
    sent, error = {}, None
    with open(folder / "selected_index.jsonl", "w", encoding="utf-8") as index_file:
        for rows in selected.values():
            for row in rows:
                index_file.write(dumps(row) + "\n")
    try:
        for split, rows in selected.items():
            (folder / split).mkdir(exist_ok=True)
            items = package.items(split, [r["trace_id"] for r in rows])
            replies = []
            for n, batch in enumerate(package.batches(items, cfg["api"]["batch_size"]), start=1):
                body = package.request_body(split, batch)
                (folder / split / f"batch-{n:04d}.json").write_text(dumps(body), encoding="utf-8")
                replies.append({"batch": n, "traces": len(batch), "reply": client.send(body)})
            with open(folder / split / "responses.jsonl", "w", encoding="utf-8") as f:
                f.writelines(dumps(r) + "\n" for r in replies)
            sent[split] = {"batches": len(replies), "traces": sum(r["traces"] for r in replies)}
    except Exception as exc:  # record what was sent before the failure, then re-raise
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        manifest = {"run": run_id, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "dry_run": client.dry_run, "endpoint": client.endpoint,
                    "selection": {"splits": selection.splits, "kinds": selection.kinds,
                                  "include": selection.include, "exclude": selection.exclude},
                    "selected": summary(selected), "sent": sent, "error": error,
                    "build_fingerprint": jev_manifest["build_fingerprint"],
                    "schemas": {"input": jev_manifest.get("input_schema"), "finding": jev_manifest.get("finding_schema")}}
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
