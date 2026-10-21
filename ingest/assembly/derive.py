"""Fields derived from stored labels rather than stored themselves: is_attack and effects."""


def is_attack(rec: dict) -> bool | None:
    """Derive whether hostile content is present.

    Args:
        rec: A record.

    Returns:
        True / False from attack_vector (`!= "none"`), or None when attack_vector is unknown.
    """
    vector = rec["labels"]["attack_vector"]
    return None if vector is None else vector != "none"


def _planned_side_effects(rec: dict) -> str | None:
    """Look up the side-effect class of the planned tool.

    Args:
        rec: A record.

    Returns:
        The planned tool's `side_effects` from tools_available, or None if there is no planned
        action or the tool is not listed.
    """
    action = rec["input"].get("planned_action")
    if not action:
        return None
    for tool in rec["input"].get("tools_available") or []:
        if tool["name"] == action["tool_name"]:
            return tool.get("side_effects")
    return None


def effects(rec: dict) -> list[str]:
    """Derive the taxonomy's effects, following `effects_derivation` in the mappings.

    Args:
        rec: A record.

    Returns:
        Sorted effect names; empty when nothing indicates an effect.
    """
    lab = rec["labels"]
    modes = lab["failure_modes"] or []
    out = set()
    if lab["action_relation"] == "harmful_user_task":
        out.add("user_harm")
    if lab["action_relation"] == "injected_task":
        side = _planned_side_effects(rec)
        if side == "external_send":
            out |= {"agent_action_abuse", "impact_outside_environment"}
        elif side in ("destructive", "financial", "code_exec"):
            out |= {"agent_action_abuse", "user_harm"}
        else:
            out |= {"agent_misalignment", "incorrect_decision_making"}
    if 13 in modes:
        out.add("agent_action_abuse")
    if "hallucination" in modes or "misinterpretation" in modes:
        out.add("incorrect_decision_making")
    return sorted(out)
