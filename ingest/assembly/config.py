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


def seed_licence_problems(dataset: str) -> list[str]:
    """Check that every dataset a derived dataset was built from may seed generation.

    A derived record inherits its seeds' licences, so a derived dataset is only admitted when each
    dataset in its `seeds_from` has `include: true` or `seed: true` in config `licences`.

    Args:
        dataset: A dataset name.

    Returns:
        One readable problem per seed dataset that is not cleared; empty when all are (or when the
        dataset declares no seeds).
    """
    gate = build_config().get("licences") or {}
    out = []
    for seed in (gate.get(dataset) or {}).get("seeds_from") or []:
        entry = gate.get(seed) or {}
        if not (entry.get("include") is True or entry.get("seed") is True):
            out.append(f"seed dataset {seed} is not cleared for generation ({entry.get('licence', 'no entry')})")
    return out


def licensed_datasets(available: list[str]) -> tuple[list[str], dict[str, str]]:
    """Split the processed datasets into those the licence gate lets into the build and the rest.

    Only `include: true` enters the build; `eval_only` datasets are left out here and read by internal
    evaluation alone (see `eval_only_datasets`). A derived dataset is also left out when any of its
    seeds is not cleared (see `seed_licence_problems`).

    Args:
        available: Datasets that have a converter (processed or not).

    Returns:
        `(included, excluded)`: included dataset names in the given order, and
        `{dataset: reason}` for each one left out (licence not cleared, evaluation only, a seed not
        cleared, or no entry in config `licences`).
    """
    gate = build_config().get("licences") or {}
    included, excluded = [], {}
    for dataset in available:
        entry = gate.get(dataset)
        if entry is None:
            excluded[dataset] = "no entry in config licences"
        elif entry.get("include") == "eval_only":
            excluded[dataset] = f"evaluation only ({entry.get('licence')})"
        elif entry.get("include") is not True:
            excluded[dataset] = f"licence not cleared ({entry.get('licence')})"
        elif seed_licence_problems(dataset):
            excluded[dataset] = "; ".join(seed_licence_problems(dataset))
        else:
            included.append(dataset)
    return included, excluded


def eval_only_datasets() -> list[str]:
    """List the datasets cleared for internal evaluation only (Tier 2).

    Returns:
        Dataset names with `include: eval_only` in config `licences`, in config order. They are never
        trained on, never used as generation seeds and never sent to an external model.
    """
    gate = build_config().get("licences") or {}
    return [d for d, entry in gate.items() if entry.get("include") == "eval_only"]


DATA_KINDS = ("real", "relabelled_real", "synthetic")


def data_kind_of_source(source: str) -> str:
    """Say what kind of data a source is (config `sources.<source>.kind`).

    Args:
        source: A source key, e.g. "toucan", "atbench_steps", "gen_inject".

    Returns:
        "real" (converted directly from a dataset; the default), "relabelled_real" (real content with
        labels located by rules or models, e.g. PROACT steps) or "synthetic" (content a model wrote).
    """
    entry = (build_config().get("sources") or {}).get(source) or {}
    kind = entry.get("kind", "real")
    if kind not in DATA_KINDS:
        raise ValueError(f"source {source}: unknown kind {kind!r}")
    return kind


def data_kind(rec: dict) -> str:
    """Say what kind of data a record is.

    Args:
        rec: A record.

    Returns:
        "real", "relabelled_real" or "synthetic" (see `data_kind_of_source`).
    """
    return data_kind_of_source(source_key(rec))


def is_derived(rec: dict) -> bool:
    """Check whether a record belongs to a derived source (it follows its seeds' split).

    Args:
        rec: A record.

    Returns:
        True if its source's config role is "derived".
    """
    return source_config(source_key(rec))["role"] == "derived"
