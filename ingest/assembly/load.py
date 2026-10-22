"""Load the processed datasets, refusing anything stale, inconsistent or tampered with."""
import hashlib
import json

from ..common.io import read_bytes
from ..common.manifest import processed_state
from ..common.paths import PROCESSED


class BuildInputError(RuntimeError):
    """Raised when the processed datasets cannot safely be combined."""


def load_processed(datasets: list[str]) -> tuple[list[dict], dict]:
    """Load and verify every processed dataset.

    Checks, per dataset: the output exists and is current (same mappings, schema, step-1 code and
    raw revision as now), and records.jsonl matches the checksum in its manifest. Across datasets:
    every manifest has the same mappings_version and schema_version.

    Args:
        datasets: Dataset names to load, e.g. ["atbench", "r_judge", "toolsafe"].

    Returns:
        `(records, manifests)`: all records, in dataset order then file order, and
        `{dataset: processed manifest}`.

    Raises:
        BuildInputError: If any check fails; the message lists every problem found.
    """
    problems, manifests, records = [], {}, []
    for dataset in datasets:
        state = processed_state(dataset)
        if state["state"] != "current":
            detail = f" ({', '.join(state['differs'])} changed)" if state["differs"] else ""
            problems.append(f"{dataset}: processed output is {state['state']}{detail}; run ingest/run.py {dataset}")
            continue
        manifest = state["manifest"]
        path = PROCESSED / dataset / "records.jsonl"
        data = read_bytes(path)  # retried while a sync client holds the file
        if hashlib.sha256(data).hexdigest() != manifest["records_sha256"]:
            problems.append(f"{dataset}: records.jsonl does not match its manifest checksum")
            continue
        manifests[dataset] = manifest
        # split on "\n" only: str.splitlines would also split on U+2028 inside JSON strings
        records.extend(json.loads(line) for line in data.decode("utf-8").split("\n") if line.strip())
    for key in ("mappings_version", "schema_version"):
        values = {m[key] for m in manifests.values()}
        if len(values) > 1:
            problems.append(f"mixed {key} across datasets: {sorted(values)}")
    if problems:
        raise BuildInputError("cannot build the training view:\n  " + "\n  ".join(problems))
    return records, manifests
