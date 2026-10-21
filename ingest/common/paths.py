"""Project locations and the versions of the spec files the converters implement."""
import json
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
TRAINING = ROOT / "data" / "training"
JEV = ROOT / "data" / "jev"
GENERATED = ROOT / "data" / "generated"      # synthetic data: runs whose content a model wrote (one folder per run)
DERIVED = ROOT / "data" / "derived"          # relabelled real data: real content, labels located by rules / models
RUN_ROOTS = (DERIVED, GENERATED)             # where converters look for runs, after data/raw
SPLITS = ROOT / "data" / "splits"            # the real-data split plan
BUILD_CONFIG_FILE = ROOT / "config" / "build.yaml"
GENERATION_CONFIG_FILE = ROOT / "config" / "generation.yaml"
DELIVER_CONFIG_FILE = ROOT / "config" / "deliver.yaml"
SCHEMA_FILE = ROOT / "label-schema" / "agent_decision_record.schema.json"
MAPPINGS_FILE = ROOT / "label-schema" / "dataset_mappings.yaml"


@lru_cache(maxsize=1)
def schema() -> dict:
    """Load the record JSON Schema (cached after the first call).

    Returns:
        The parsed contents of label-schema/agent_decision_record.schema.json.
    """
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def mappings() -> dict:
    """Load the dataset mappings (cached after the first call).

    Returns:
        The parsed contents of label-schema/dataset_mappings.yaml.
    """
    return yaml.safe_load(MAPPINGS_FILE.read_text(encoding="utf-8"))


def schema_version() -> str:
    """Get the schema version records are written against.

    Returns:
        The schema's `schema_version` const, e.g. "0.6.0".
    """
    return schema()["properties"]["schema_version"]["const"]


def mappings_version() -> str:
    """Get the mappings version written into every record.

    Returns:
        The YAML's top-level `mappings_version`, e.g. "0.6.2".
    """
    return mappings()["mappings_version"]


def generated_pins() -> dict:
    """Read which generated run each derived dataset uses.

    Returns:
        `{dataset: run id}` from `pins` in config/generation.yaml (empty if the file or key is missing).
    """
    if not GENERATION_CONFIG_FILE.exists():
        return {}
    return (yaml.safe_load(GENERATION_CONFIG_FILE.read_text(encoding="utf-8")) or {}).get("pins") or {}


def raw_snapshot(dataset: str) -> Path:
    """Find a dataset's pinned input folder.

    Downloaded datasets live in data/raw/<dataset>/<commit>/. A dataset folder may also hold
    companion downloads (e.g. InjecAgent's model outputs); the snapshot is the folder whose manifest
    names the dataset itself. Relabelled real data lives in data/derived/<dataset>/<run>/ and synthetic
    data in data/generated/<dataset>/<run>/: the run pinned in config/generation.yaml `pins`, or the
    only run if there is exactly one.

    Args:
        dataset: Dataset name, e.g. "atbench", a companion's manifest name, e.g.
            "injecagent_results" (looked up under data/raw/injecagent/), or a derived or generated
            dataset, e.g. "atbench_steps" or "gen_inject".

    Returns:
        The input folder; its manifest.json has `"dataset": <dataset>`.

    Raises:
        RuntimeError: If there is not exactly one such folder (or the pinned run does not exist).
    """
    root = next((r for r in RUN_ROOTS if (r / dataset).is_dir()), None)
    if not (RAW / dataset).is_dir() and root is not None:
        pinned = generated_pins().get(dataset)
        runs = [p for p in (root / dataset).iterdir() if p.is_dir() and (p / "manifest.json").exists()]
        if pinned:
            runs = [p for p in runs if p.name == pinned]
        if len(runs) != 1:
            raise RuntimeError(f"expected one run of {dataset} in {root / dataset} "
                               f"(pin one in config/generation.yaml `pins`), found {len(runs)}")
        return runs[0]
    parent = RAW / dataset if (RAW / dataset).is_dir() else RAW / dataset.split("_")[0]
    folders = [p for p in parent.iterdir() if p.is_dir() and (p / "manifest.json").exists()
               and json.loads((p / "manifest.json").read_text(encoding="utf-8")).get("dataset") == dataset]
    if len(folders) != 1:
        raise RuntimeError(f"expected one snapshot folder for {dataset} in {parent}, found {len(folders)}")
    return folders[0]


def has_input(dataset: str) -> bool:
    """Check whether a dataset's input folder exists (a generated dataset may not be generated yet).

    Args:
        dataset: Dataset name.

    Returns:
        True if `raw_snapshot` finds exactly one input folder.
    """
    try:
        raw_snapshot(dataset)
    except (RuntimeError, FileNotFoundError):
        return False
    return True
