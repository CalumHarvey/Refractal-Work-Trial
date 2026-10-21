"""Rule registry: each converter implements the YAML rules as functions registered under the same ids.

The YAML in label-schema/dataset_mappings.yaml is the specification; these functions are the
implementation. `missing_from_code` / `missing_from_yaml` keep the two in sync (see tests).
"""
from collections import Counter
from typing import Callable

from .paths import mappings

RuleFn = Callable[[dict, "Record"], bool]  # returns True if the rule fired  # noqa: F821


class RuleSet:
    """The rules one converter implements, applied in registration order.

    Attributes:
        dataset: Key of the dataset under `section` in the mappings YAML.
        section: "datasets" or "attack_content_pool".
        hits: Number of records each rule fired on in the current run.
    """

    def __init__(self, dataset: str, section: str = "datasets"):
        """Create an empty rule set bound to one dataset's mappings entry.

        Args:
            dataset: Key of the dataset in the mappings YAML, e.g. "atbench".
            section: "datasets" (default) or "attack_content_pool".
        """
        self.dataset = dataset
        self.section = section
        self._rules: list[tuple[str, RuleFn]] = []
        self.hits: Counter = Counter()

    def rule(self, rule_id: str):
        """Decorator that registers a rule function under its mappings rule id.

        Args:
            rule_id: The id from the mappings YAML, e.g. "at.safe".

        Returns:
            A decorator that registers the function and returns it unchanged.
        """
        def register(fn: RuleFn) -> RuleFn:
            """Register the decorated function under `rule_id`.

            Args:
                fn: Rule function taking `(src, rec)` and returning True if it fired.

            Returns:
                The same function, unchanged.

            Raises:
                ValueError: If `rule_id` is already registered.
            """
            if any(rid == rule_id for rid, _ in self._rules):
                raise ValueError(f"duplicate rule id {rule_id}")
            self._rules.append((rule_id, fn))
            return fn
        return register

    def apply(self, src: dict, rec) -> None:
        """Run every rule, in registration order, on one raw item.

        Each rule checks its own `when` condition and returns True if it fired.

        Args:
            src: The raw item.
            rec: The Record being built.

        Returns:
            None. Fired rules are counted in `hits`.
        """
        for rule_id, fn in self._rules:
            if fn(src, rec):
                self.hits[rule_id] += 1

    @property
    def ids(self) -> list[str]:
        """Get the rule ids implemented in code.

        Returns:
            Rule ids in application order.
        """
        return [rid for rid, _ in self._rules]

    def yaml_ids(self) -> list[str]:
        """Get the rule ids the mappings YAML defines for this dataset.

        Returns:
            Rule ids in YAML order.
        """
        spec = mappings()[self.section][self.dataset]
        return [r["id"] for r in spec.get("rules", []) if "id" in r]

    def missing_from_code(self) -> list[str]:
        """Find YAML rules without an implementation.

        Returns:
            YAML rule ids that are not registered in code; empty when in sync.
        """
        return [rid for rid in self.yaml_ids() if rid not in self.ids]

    def missing_from_yaml(self) -> list[str]:
        """Find implemented rules the YAML does not define.

        Returns:
            Registered rule ids missing from the YAML; empty when in sync.
        """
        return [rid for rid in self.ids if rid not in self.yaml_ids()]
