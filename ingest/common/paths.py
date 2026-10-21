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
BUILD_CONFIG_FILE = ROOT / "config" / "build.yaml"
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


def raw_snapshot(dataset: str) -> Path:
    """Find a dataset's pinned raw snapshot folder.

    A dataset folder may also hold companion downloads (e.g. InjecAgent's model outputs); the
    snapshot is the folder whose manifest names the dataset itself.

    Args:
        dataset: Dataset name, e.g. "atbench", or a companion's manifest name, e.g.
            "injecagent_results" (looked up under data/raw/injecagent/).

    Returns:
        The single folder under data/raw/<dataset>/ (or data/raw/<parent>/ for a companion) whose
        manifest.json has `"dataset": <dataset>`.

    Raises:
        RuntimeError: If there is not exactly one such folder.
    """
    parent = RAW / dataset if (RAW / dataset).is_dir() else RAW / dataset.split("_")[0]
    folders = [p for p in parent.iterdir() if p.is_dir() and (p / "manifest.json").exists()
               and json.loads((p / "manifest.json").read_text(encoding="utf-8")).get("dataset") == dataset]
    if len(folders) != 1:
        raise RuntimeError(f"expected one snapshot folder for {dataset} in {parent}, found {len(folders)}")
    return folders[0]
