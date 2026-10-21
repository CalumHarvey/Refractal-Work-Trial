"""State of a dataset's processed output relative to the current code, spec and raw snapshot."""
import json

from .io import code_fingerprint, manifest_path
from .paths import mappings_version, raw_snapshot, schema_version


def processed_state(dataset: str) -> dict:
    """Compare a dataset's processed manifest with what the current code and spec would produce.

    An output is stale if any of these differ from now: mappings version, schema version, code
    fingerprint of ingest/, or the raw snapshot's revision.

    Args:
        dataset: Dataset name, e.g. "toolsafe".

    Returns:
        `{"state": "current" | "stale" | "missing", "differs": [what changed], "manifest": dict | None}`.
    """
    path = manifest_path(dataset)
    if not path.exists():
        return {"state": "missing", "differs": [], "manifest": None}
    made = json.loads(path.read_text(encoding="utf-8"))
    now = {"mappings_version": mappings_version(), "schema_version": schema_version(),
           "code_fingerprint": code_fingerprint()}
    differs = [k for k, v in now.items() if made.get(k) != v]
    raw_rev = json.loads((raw_snapshot(dataset) / "manifest.json").read_text(encoding="utf-8"))["revision"]
    if made.get("raw_revision") != raw_rev:
        differs.append("raw_revision")
    return {"state": "stale" if differs else "current", "differs": differs, "manifest": made}
