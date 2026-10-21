"""Building one AgentDecisionRecord: labels are only ever set together with their provenance."""
from collections import Counter

from .paths import mappings_version, schema_version

LABELS = ("decision", "attack_vector", "failure_modes", "action_relation",
          "outcome", "adversarial_locations", "hard_negative")
CONVERTER_RULE_HITS: Counter = Counter()


class Record:
    """One AgentDecisionRecord under construction.

    Converters fill `source` and `input` directly and set labels only through `set`,
    `add_modes` and `set_no_modes`, so every label carries its provenance. `build` applies the
    shared converter rules and returns the record as a dict.

    Attributes:
        dataset: Dataset name.
        granularity: "text", "step", "trajectory" or "outcome".
        source: The record's `source` section, including `group_ids`.
        input: The decision context shown to the model.
        labels: The seven labels, null until a rule sets them.
        provenance: `{label: {"origin", "rule"}}`; failure_modes holds one entry per mode.
        needs_backfill: Labels a later stage must fill.
        meta: Optional `meta` section.
        scratch: Converter working state shared between rules; never written out.
    """

    def __init__(self, dataset: str, original_id: str, granularity: str):
        """Start an empty record: every label null, no provenance, every group_ids axis null.

        Args:
            dataset: Dataset name, written to `source.dataset`.
            original_id: The item's id in the raw dataset, written to `source.original_id`.
            granularity: "text", "step", "trajectory" or "outcome".
        """
        self.dataset = dataset
        self.granularity = granularity
        self.source = {"dataset": dataset, "original_id": original_id,
                       "group_ids": {"task": None, "attack": None, "trajectory": None, "author": None}}
        self.input: dict = {"messages": []}
        self.labels: dict = {name: None for name in LABELS}
        self.provenance: dict = {}
        self.needs_backfill: list[str] = []
        self.meta: dict = {}
        self.scratch: dict = {}  # converter working state; never written out

    # ---- labels -------------------------------------------------------------------------
    def set(self, label: str, value, origin: str, rule: str) -> None:
        """Set a scalar label together with its provenance.

        Args:
            label: Any label except failure_modes (which has `add_modes` / `set_no_modes`).
            value: The label value.
            origin: Provenance origin, e.g. "given" or "rule_inferred".
            rule: Id of the rule setting it.

        Returns:
            None.

        Raises:
            ValueError: If `label` is "failure_modes".
        """
        if label == "failure_modes":
            raise ValueError("use add_modes / set_no_modes for failure_modes")
        self.labels[label] = value
        self.provenance[label] = {"origin": origin, "rule": rule}

    def add_modes(self, modes, origin: str, rule: str) -> None:
        """Add failure modes, recording provenance for each new one.

        Modes already present keep their original provenance. A previous "verified none" entry is
        dropped once any mode is added.

        Args:
            modes: Modes to add (integers 1-23 or named modes); may be empty.
            origin: Provenance origin for the new modes.
            rule: Id of the rule adding them.

        Returns:
            None.
        """
        current = self.labels["failure_modes"] or []
        entries = [e for e in self.provenance.get("failure_modes", []) if e["mode"] is not None]
        for mode in modes:
            if mode not in current:
                current.append(mode)
                entries.append({"mode": mode, "origin": origin, "rule": rule})
        if current:
            self.labels["failure_modes"] = current
            self.provenance["failure_modes"] = entries

    def set_no_modes(self, origin: str, rule: str) -> None:
        """Mark failure modes as verified empty, unless a rule has already added a mode.

        Args:
            origin: Provenance origin of the "none" verdict.
            rule: Id of the rule making it.

        Returns:
            None.
        """
        if not self.labels["failure_modes"]:
            self.labels["failure_modes"] = []
            self.provenance["failure_modes"] = [{"mode": None, "origin": origin, "rule": rule}]

    def flag_backfill(self, label: str) -> None:
        """Ask the later backfill stage to (re)fill a label on this record.

        Args:
            label: The label to fill; added to `needs_backfill` once.

        Returns:
            None.
        """
        if label not in self.needs_backfill:
            self.needs_backfill.append(label)

    # ---- shared converter rules (`converter_rules` in the mappings) --------------------
    def apply_converter_rules(self) -> None:
        """Apply the mappings' `converter_rules`, which hold for every dataset.

        cv.hard_negative_non_allow: BLOCK or REVIEW sets hard_negative false.
        cv.fm_missing: null failure modes (except on outcome records) are flagged for backfill.
        cv.fm_unsafe_empty: BLOCK or REVIEW with no failure mode is flagged for backfill.

        Returns:
            None. Hits are counted in CONVERTER_RULE_HITS.
        """
        lab = self.labels
        if lab["decision"] in ("BLOCK", "REVIEW") and lab["hard_negative"] is None:
            self.set("hard_negative", False, "by_construction", "cv.hard_negative_non_allow")
            CONVERTER_RULE_HITS["cv.hard_negative_non_allow"] += 1
        if lab["failure_modes"] is None and self.granularity != "outcome":
            self.flag_backfill("failure_modes")
            CONVERTER_RULE_HITS["cv.fm_missing"] += 1
        if lab["decision"] in ("BLOCK", "REVIEW") and lab["failure_modes"] == []:
            self.flag_backfill("failure_modes")
            CONVERTER_RULE_HITS["cv.fm_unsafe_empty"] += 1

    # ---- output ---------------------------------------------------------------------------
    def build(self, record_id: str) -> dict:
        """Apply the converter rules and assemble the record.

        Args:
            record_id: Stable id for the record, e.g. "atbench:170".

        Returns:
            The record as a dict in schema format. It is not validated here; see `validate.problems`.
        """
        self.apply_converter_rules()
        rec = {
            "record_id": record_id,
            "schema_version": schema_version(),
            "mappings_version": mappings_version(),
            "source": self.source,
            "granularity": self.granularity,
            "input": self.input,
            "labels": self.labels,
            "provenance": self.provenance,
            "needs_backfill": sorted(self.needs_backfill),
        }
        if self.meta:
            rec["meta"] = self.meta
        return rec
