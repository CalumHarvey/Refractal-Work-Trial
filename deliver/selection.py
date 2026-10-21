"""Which traces to send: a selection over split, data kind and dataset, applied to data/jev/<split>/index.jsonl."""
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache

import yaml

from ingest.assembly.config import DATA_KINDS
from ingest.assembly.split import SPLITS
from ingest.common.io import read_jsonl
from ingest.common.paths import DELIVER_CONFIG_FILE, JEV


@lru_cache(maxsize=1)
def deliver_config() -> dict:
    """Load config/deliver.yaml (cached after the first call).

    Returns:
        The parsed configuration.
    """
    return yaml.safe_load(DELIVER_CONFIG_FILE.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Selection:
    """What to send.

    Attributes:
        splits: Splits to send.
        kinds: Data kinds to send: "real", "relabelled_real", "synthetic".
        include: Datasets to send (empty = all in the selected kinds).
        exclude: Datasets never to send.
    """

    splits: tuple[str, ...]
    kinds: tuple[str, ...]
    include: tuple[str, ...] = field(default=())
    exclude: tuple[str, ...] = field(default=())

    def __post_init__(self):
        """Check every value is known.

        Raises:
            ValueError: If a split or kind is not recognised.
        """
        unknown = [s for s in self.splits if s not in SPLITS] + [k for k in self.kinds if k not in DATA_KINDS]
        if unknown:
            raise ValueError(f"unknown split or kind: {unknown} (splits {SPLITS}, kinds {DATA_KINDS})")

    @classmethod
    def from_config(cls, **overrides) -> "Selection":
        """Build the selection from config `selection`, with optional overrides.

        Args:
            **overrides: Any of splits, kinds, include, exclude; None leaves the config value.

        Returns:
            The selection.
        """
        cfg = deliver_config()["selection"]
        values = {"splits": cfg["splits"], "kinds": cfg["kinds"],
                  "include": cfg["datasets"].get("include") or [], "exclude": cfg["datasets"].get("exclude") or []}
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**{k: tuple(v) for k, v in values.items()})

    def keeps(self, entry: dict) -> bool:
        """Check whether one index entry is selected.

        Args:
            entry: A data/jev index row (data_kind, dataset).

        Returns:
            True if its kind is selected, its dataset is included (or no include list is set), and it
            is not excluded.
        """
        return (entry["data_kind"] in self.kinds
                and (not self.include or entry["dataset"] in self.include)
                and entry["dataset"] not in self.exclude)


def read_index(split: str) -> list[dict]:
    """Read a split's local index.

    Args:
        split: Split name.

    Returns:
        Index rows (one per trace); empty if the split has no file.
    """
    return read_jsonl(JEV / split / "index.jsonl")


def select(selection: Selection) -> dict[str, list[dict]]:
    """Apply a selection to every selected split.

    Args:
        selection: What to send.

    Returns:
        `{split: [index rows of the selected traces]}`.
    """
    return {split: [e for e in read_index(split) if selection.keeps(e)] for split in selection.splits}


def summary(selected: dict[str, list[dict]]) -> dict:
    """Count the selected traces.

    Args:
        selected: Output of `select`.

    Returns:
        `{split: {"traces", "by_kind", "by_dataset", "by_decision"}}`.
    """
    return {split: {"traces": len(rows), "by_kind": dict(Counter(r["data_kind"] for r in rows)),
                    "by_dataset": dict(Counter(r["dataset"] for r in rows)),
                    "by_decision": dict(Counter(str(r["decision"]) for r in rows))}
            for split, rows in selected.items()}
