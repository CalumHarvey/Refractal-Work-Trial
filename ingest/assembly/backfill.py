"""Failure-mode backfill, deterministic rules only (`failure_mode_backfill`, method bf.rules).

The LLM-judge and classifier methods wait for a calibration set. Records the rules cannot settle
keep their `needs_backfill` flag. Modes with origin given / by_construction / human_verified are
never overwritten; rules only add modes.
"""
from collections import Counter

RULE_ID = "bf.rules"
TRUST_MODE = {"tool_output": 16, "retrieved": 16, "memory": 14, "inter_agent": 2, "principal": 2}


def rule_modes(rec: dict) -> list:
    """Apply the backfill rules to one record.

    Args:
        rec: A record flagged for failure-mode backfill.

    Returns:
        The modes the rules support (possibly empty), without duplicates, in rule order.
    """
    lab, messages = rec["labels"], rec["input"]["messages"]
    modes = []
    for loc in lab["adversarial_locations"] or []:
        if loc["kind"] == "tool":
            modes.append(12)
        elif loc["kind"] == "system_prompt":
            modes.append(5)
        elif loc["kind"] == "message" and loc.get("message_index") is not None:
            mode = TRUST_MODE.get(messages[loc["message_index"]]["trust"])
            if mode:
                modes.append(mode)
    if lab["decision"] == "BLOCK" and lab["attack_vector"] == "none" and lab["action_relation"] == "harmful_user_task":
        modes.append("principal_misuse")
    if lab["decision"] == "BLOCK" and lab["action_relation"] == "injected_task":
        modes.append(22)
    return list(dict.fromkeys(modes))


def backfill(records: list[dict]) -> dict:
    """Run the rules on every record flagged for failure-mode backfill, in place.

    Args:
        records: In-memory records (copies; processed files are never touched).

    Returns:
        `{"flagged", "filled", "still_flagged", "modes_added"}` counts for the build report.
    """
    stats = Counter()
    for rec in records:
        if "failure_modes" not in rec["needs_backfill"]:
            continue
        stats["flagged"] += 1
        modes = rule_modes(rec)
        if not modes:
            stats["still_flagged"] += 1
            continue
        current = rec["labels"]["failure_modes"] or []
        entries = [e for e in rec["provenance"].get("failure_modes", []) if e["mode"] is not None]
        for mode in modes:
            if mode not in current:
                current.append(mode)
                entries.append({"mode": mode, "origin": "rule_inferred", "rule": RULE_ID})
                stats[f"mode_{mode}"] += 1
        rec["labels"]["failure_modes"] = current
        rec["provenance"]["failure_modes"] = entries
        rec["needs_backfill"] = [label for label in rec["needs_backfill"] if label != "failure_modes"]
        stats["filled"] += 1
    return {"flagged": stats["flagged"], "filled": stats["filled"], "still_flagged": stats["still_flagged"],
            "modes_added": {k[5:]: v for k, v in stats.items() if k.startswith("mode_")}}
