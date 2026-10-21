"""Load the processed datasets, refusing anything stale, inconsistent or tampered with."""
import hashlib
import json

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
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["records_sha256"]:
            problems.append(f"{dataset}: records.jsonl does not match its manifest checksum")
            continue
        manifests[dataset] = manifest
        with open(path, encoding="utf-8") as f:
            records.extend(json.loads(line) for line in f)
    for key in ("mappings_version", "schema_version"):
        values = {m[key] for m in manifests.values()}
        if len(values) > 1:
            problems.append(f"mixed {key} across datasets: {sorted(values)}")
    if problems:
        raise BuildInputError("cannot build the training view:\n  " + "\n  ".join(problems))
    return records, manifests
