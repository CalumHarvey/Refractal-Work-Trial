"""Exact deduplication across datasets: identical model input (including the planned action)."""
import hashlib
import json
from collections import defaultdict

ORIGIN_RANK = {"human_verified": 4, "given": 3, "by_construction": 3, "rule_inferred": 2, "model_inferred": 1}


def input_key(rec: dict) -> str:
    """Hash what the model sees, so identical decision points collide.

    Args:
        rec: A record.

    Returns:
        SHA-256 hex digest of the canonical JSON of the record's input plus its granularity.
    """
    payload = json.dumps({"granularity": rec["granularity"], "input": rec["input"]}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _strength(rec: dict) -> tuple:
    """Rank a record among duplicates: strongest decision provenance first, then record_id.

    Args:
        rec: A record.

    Returns:
        A sort key; smaller sorts first.
    """
    origin = (rec["provenance"].get("decision") or {}).get("origin")
    return (-ORIGIN_RANK.get(origin, 0), rec["record_id"])


def deduplicate(records: list[dict]) -> tuple[list[dict], dict]:
    """Collapse records whose model input is identical, keeping the strongest one.

    Args:
        records: All records.

    Returns:
        `(kept, report)`. report has the number of duplicate groups, records removed, and the
        groups whose copies disagree on the decision (kept for audit, with every member's id and
        decision).
    """
    groups = defaultdict(list)
    for rec in records:
        groups[input_key(rec)].append(rec)
    kept, removed, conflicts = [], 0, []
    for members in groups.values():
        members.sort(key=_strength)
        kept.append(members[0])
        removed += len(members) - 1
        decisions = {m["labels"]["decision"] for m in members}
        if len(decisions) > 1:
            conflicts.append([{"record_id": m["record_id"], "decision": m["labels"]["decision"]} for m in members])
    kept.sort(key=lambda r: r["record_id"])
    return kept, {"duplicate_groups": sum(len(m) > 1 for m in groups.values()), "removed": removed,
                  "conflicting_groups": len(conflicts), "conflicts": conflicts[:50]}
