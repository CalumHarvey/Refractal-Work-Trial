"""Build configuration (config/build.yaml) and the fingerprint of everything a build depends on."""
import hashlib
from functools import lru_cache

import yaml

from ..common.io import code_fingerprint
from ..common.paths import BUILD_CONFIG_FILE, MAPPINGS_FILE


@lru_cache(maxsize=1)
def build_config() -> dict:
    """Load the build configuration (cached after the first call).

    Returns:
        The parsed contents of config/build.yaml.
    """
    return yaml.safe_load(BUILD_CONFIG_FILE.read_text(encoding="utf-8"))


def build_fingerprint() -> str:
    """Fingerprint the inputs that define a build, other than the processed data itself.

    Returns:
        The first 16 hex characters of a SHA-256 over config/build.yaml, the mappings YAML (which
        holds the confidence priors and calibration registry) and all ingest/ code.
    """
    h = hashlib.sha256()
    h.update(BUILD_CONFIG_FILE.read_bytes())
    h.update(MAPPINGS_FILE.read_bytes())
    h.update(code_fingerprint(exclude=()).encode())
    return h.hexdigest()[:16]


def source_key(rec: dict) -> str:
    """Name the source a record belongs to, as used in config `sources`.

    ToolSafe mixes three benchmarks, so its source is "toolsafe/<origin benchmark>"; every other
    dataset is its own source.

    Args:
        rec: A processed record.

    Returns:
        e.g. "toolsafe/asb", "atbench".
    """
    dataset = rec["source"]["dataset"]
    if dataset == "toolsafe":
        return f"toolsafe/{rec['record_id'].split(':')[1]}"
    return dataset


def source_config(source: str) -> dict:
    """Look up a source's role and ratios.

    Args:
        source: A source key from `source_key`.

    Returns:
        `{"role": "train" | "holdout", "ratios": {...}}`, with the default ratios filled in.

    Raises:
        KeyError: If the source is not listed in config `sources` (every source must be assigned).
    """
    cfg = build_config()
    entry = dict(cfg["sources"][source])
    entry.setdefault("ratios", cfg["split"]["ratios"])
    return entry


def licensed_datasets(available: list[str]) -> tuple[list[str], dict[str, str]]:
    """Split the processed datasets into those the licence gate lets into the build and the rest.

    Args:
        available: Datasets that have a converter (processed or not).

    Returns:
        `(included, excluded)`: included dataset names in the given order, and
        `{dataset: reason}` for each one left out (licence not cleared, or no entry in config
        `licences`).
    """
    gate = build_config().get("licences") or {}
    included, excluded = [], {}
    for dataset in available:
        entry = gate.get(dataset)
        if entry is None:
            excluded[dataset] = "no entry in config licences"
        elif not entry.get("include"):
            excluded[dataset] = f"licence not cleared ({entry.get('licence')})"
        else:
            included.append(dataset)
    return included, excluded

