"""Training weights: decision confidence x source balance x class balance x hard-negative multiplier.

Balancing reweights rather than drops data (decided 2026-10-20). Factors are computed per head on
the train split only and clipped; records in other splits get weight 1.
"""
from collections import Counter

from .config import build_config, source_key


def head(rec: dict) -> str | None:
    """Name the decision head a record trains.

    Args:
        rec: A record.

    Returns:
        "step" or "trajectory" for records with those granularities, else None.
    """
    return rec["granularity"] if rec["granularity"] in ("step", "trajectory") else None


def _clip(value: float) -> float:
    """Clip a balance factor to the configured range.

    Args:
        value: The raw factor.

    Returns:
        The factor within [min_factor, max_factor].
    """
    cfg = build_config()["weights"]
    return max(cfg["min_factor"], min(cfg["max_factor"], value))


def compute(records: list[dict], splits: dict[str, str], decision_conf: dict[str, float]) -> dict[str, float]:
    """Compute a training weight for every record.

    Source factor: each source contributes equal total weight within a head. Class factor: within
    a source, each decision class contributes equally. Both are clipped, then the weights of each
    head's train split are rescaled to average 1.

    Args:
        records: All records.
        splits: `{record_id: split}`.
        decision_conf: `{record_id: resolved confidence of the decision}` (missing -> 1.0).

    Returns:
        `{record_id: weight}`; 1.0 for every record outside the train split or without a head.
    """
    cfg = build_config()["weights"]
    weights = {r["record_id"]: 1.0 for r in records}
    for name in ("step", "trajectory"):
        train = [r for r in records if head(r) == name and splits[r["record_id"]] == "train"]
        if not train:
            continue
        by_source = Counter(source_key(r) for r in train)
        by_class = Counter((source_key(r), r["labels"]["decision"]) for r in train)
        classes_per_source = Counter(s for s, _ in by_class)
        raw = {}
        for r in train:
            src, dec = source_key(r), r["labels"]["decision"]
            w = decision_conf.get(r["record_id"], 1.0)
            if cfg["balance_sources"]:
                w *= _clip(len(train) / (len(by_source) * by_source[src]))
            if cfg["balance_decisions"]:
                w *= _clip(by_source[src] / (classes_per_source[src] * by_class[(src, dec)]))
            if r["labels"]["hard_negative"] is True:
                w *= cfg["hard_negative_multiplier"]
            raw[r["record_id"]] = w
        mean = sum(raw.values()) / len(raw)
        weights.update({rid: round(w / mean, 6) for rid, w in raw.items()})
    return weights


def summary(records: list[dict], splits: dict[str, str], weights: dict[str, float]) -> dict:
    """Summarise effective weight by source and decision on the train split.

    Args:
        records: All records.
        splits: `{record_id: split}`.
        weights: `{record_id: weight}`.

    Returns:
        `{head: {"records": n, "weight_share_by_source": {...}, "weight_share_by_decision": {...},
        "min": w, "max": w}}`.
    """
    out = {}
    for name in ("step", "trajectory"):
        train = [r for r in records if head(r) == name and splits[r["record_id"]] == "train"]
        if not train:
            continue
        total = sum(weights[r["record_id"]] for r in train)
        out[name] = {"records": len(train),
                     "weight_share_by_source": _share(train, weights, source_key, total),
                     "weight_share_by_decision": _share(train, weights, lambda r: r["labels"]["decision"], total),
                     "min": min(weights[r["record_id"]] for r in train),
                     "max": max(weights[r["record_id"]] for r in train)}
    return out


def _share(records: list[dict], weights: dict[str, float], key, total: float) -> dict:
    """Fraction of total weight per group.

    Args:
        records: Records to summarise.
        weights: `{record_id: weight}`.
        key: Function mapping a record to its group.
        total: Total weight of `records`.

    Returns:
        `{group: share}`, rounded to 4 decimals.
    """
    acc = Counter()
    for r in records:
        acc[key(r)] += weights[r["record_id"]]
    return {str(k): round(v / total, 4) for k, v in sorted(acc.items(), key=lambda kv: str(kv[0]))}
