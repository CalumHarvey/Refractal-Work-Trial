"""Resolve each label's confidence and calibration status from its provenance rule.

Order (dataset_mappings.yaml, "Confidence"): a record-specific confidence on the provenance entry;
else calibration.rules[rule][label] if audited; else the rule's `confidence`; else the dataset's
`confidence`; else default_confidence[label_source] (label_source: rule, then dataset; converter and
backfill rules fall back to their origin).
"""
from functools import lru_cache

from ..common.paths import mappings

SCALAR_LABELS = ("decision", "attack_vector", "action_relation", "outcome", "adversarial_locations", "hard_negative")
# Origin -> default_confidence key, for rules with no label_source (converter_rules, backfill).
ORIGIN_SOURCE = {"by_construction": "by_construction", "given": "human", "rule_inferred": "rule",
                 "model_inferred": "llm_judge", "human_verified": "human"}


def _number(value):
    """Keep numeric confidences; table entries such as "calibrated" mean "no prior".

    Args:
        value: A confidence value from the YAML.

    Returns:
        The value as a float, or None if it is not a number.
    """
    return float(value) if isinstance(value, (int, float)) else None


@lru_cache(maxsize=1)
def rule_index() -> dict[str, dict]:
    """Index every rule in the mappings by id.

    Returns:
        `{rule_id: {"confidence", "dataset_confidence", "label_source", "origin"}}` for dataset rules,
        attack-content-pool rules, converter rules and backfill methods.
    """
    m = mappings()
    index = {}
    for section in ("datasets", "attack_content_pool"):
        for spec in (m.get(section) or {}).values():
            for r in spec.get("rules", []):
                index[r["id"]] = {"confidence": _number(r.get("confidence")),
                                  "dataset_confidence": _number(spec.get("confidence")),
                                  "label_source": r.get("label_source") or spec.get("label_source"),
                                  "origin": r.get("origin") or spec.get("origin")}
    for r in m.get("converter_rules", []):
        index[r["id"]] = {"confidence": None, "dataset_confidence": None, "label_source": None,
                          "origin": r.get("origin", "by_construction")}
    for method in m.get("failure_mode_backfill", {}).get("methods", []):
        index[method["id"]] = {"confidence": _number(method.get("confidence")), "dataset_confidence": None,
                               "label_source": None, "origin": method.get("origin")}
    return index


def resolve(rule: str, label: str, origin: str, record_value=None) -> tuple[float | None, str]:
    """Resolve one label's confidence and calibration status.

    Combined ids ("a+b", when two rules built one label) take the weaker of the parts.

    Args:
        rule: The provenance rule id.
        label: The label name, used to look up audited values.
        origin: The provenance origin, used when the rule has no label_source.
        record_value: A record-specific confidence from the provenance entry, if any.

    Returns:
        `(confidence, status)`. status is "record_specific", the audited entry's status, or the
        calibration default ("uncalibrated"). confidence is None only if no prior exists at all.
    """
    m = mappings()
    if record_value is not None:
        return float(record_value), "record_specific"
    parts = rule.split("+")
    if len(parts) > 1:
        resolved = [resolve(p, label, origin) for p in parts]
        known = [r for r in resolved if r[0] is not None]
        return min(known) if known else (None, resolved[0][1])
    audited = ((m.get("calibration", {}).get("rules") or {}).get(rule) or {}).get(label)
    if audited and audited.get("precision") is not None:
        return float(audited["precision"]), audited.get("status", "audited")
    status = m.get("calibration", {}).get("default_status", "uncalibrated")
    info = rule_index().get(rule)
    if info is None:
        raise KeyError(f"provenance rule {rule!r} is not defined in the mappings")
    for value in (info["confidence"], info["dataset_confidence"]):
        if value is not None:
            return value, status
    key = info["label_source"] or ORIGIN_SOURCE.get(info["origin"] or origin)
    return _number(m.get("default_confidence", {}).get(key)), status


def resolve_record(rec: dict) -> tuple[dict, dict]:
    """Resolve confidence and status for every non-null label of a record.

    failure_modes gets the weakest per-mode confidence (matching the documented convention).

    Args:
        rec: A record (labels and provenance as written by step 1 or the backfill).

    Returns:
        `(label_confidence, label_status)`, both `{label: value}` over the non-null labels.
    """
    conf, status = {}, {}
    for label in SCALAR_LABELS:
        p = rec["provenance"].get(label)
        if rec["labels"][label] is not None and p:
            conf[label], status[label] = resolve(p["rule"], label, p["origin"], p.get("confidence"))
    entries = rec["provenance"].get("failure_modes") or []
    if rec["labels"]["failure_modes"] is not None and entries:
        resolved = [resolve(e["rule"], "failure_modes", e["origin"], e.get("confidence")) for e in entries]
        known = [r for r in resolved if r[0] is not None]
        conf["failure_modes"], status["failure_modes"] = min(known) if known else resolved[0]
    return conf, status
