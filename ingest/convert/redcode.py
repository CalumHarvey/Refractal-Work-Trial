"""RedCode-Exec -> AgentDecisionRecords (one step record per risky case and request variant).

Spec: `datasets.redcode` in label-schema/dataset_mappings.yaml. A user asks for a script (RedCode's
Text_summary or Text_details); the agent's planned action runs the case's code on a real shell or Python
execution tool taken from TOUCAN, so the tool name is shared with benign steps. The decision comes from
the case's risk category (BLOCK or REVIEW); code-quality categories are left out, counted in the report.
"""
import json
import re
from collections import Counter
from pathlib import Path

from ..common.paths import mappings
from ..common.record import Record
from ..common.rules import RuleSet
from ..common.text import sha1_12

DATASET = "redcode"
RULES = RuleSet(DATASET)
LANGUAGES = {"bash2text_dataset_json": "bash", "py2text_dataset_json": "python"}
VARIANT_FIELD = {"summary": "Text_summary", "details": "Text_details"}
STATS: Counter = Counter()


def _spec() -> dict:
    """Read the dataset's mapping entry.

    Returns:
        `datasets.redcode` from the mappings YAML.
    """
    return mappings()["datasets"][DATASET]


def category_table() -> dict[int, dict]:
    """The risk-category table of rule rc.category.

    Returns:
        `{category index: {"name", "decision", "modes"} or {"name", "exclude": True}}`.
    """
    rule = next(r for r in _spec()["rules"] if r["id"] == "rc.category")
    return {int(k): v for k, v in rule["table"].items()}


def host_tool(language: str, case_key: str) -> dict:
    """Choose the real execution tool a case runs on (stable for the case).

    Args:
        language: "bash" or "python".
        case_key: The case's id, e.g. "bash:7_12".

    Returns:
        The host tool spec from the mappings: name, argument, description, parameters_schema.
    """
    tools = _spec()["host_tools"][language]
    return tools[int(sha1_12("host|" + case_key), 16) % len(tools)]


# ---- raw input ---------------------------------------------------------------------------
def iter_source(snapshot: Path):
    """Yield one item per kept case and request variant.

    Args:
        snapshot: The RedCode pinned-commit folder.

    Yields:
        `(original_id, item)`: original_id is "<language>:<Index>:<variant>"; item holds the case,
        its language, category index, variant and the category entry.
    """
    STATS.clear()
    table = category_table()
    variants = _spec()["selection"]["variants"]
    root = snapshot / "dataset" / "RedCode-Exec"
    for folder, language in LANGUAGES.items():
        files = sorted((root / folder).glob("*.json"), key=lambda p: int(re.search(r"index(\d+)", p.name).group(1)))
        for path in files:
            category = int(re.search(r"index(\d+)", path.name).group(1))
            entry = table[category]
            for case in json.loads(path.read_text(encoding="utf-8")):
                STATS[f"cases_{language}"] += 1
                if entry.get("exclude"):
                    STATS["cases_excluded_code_quality"] += 1
                    continue
                for variant in variants:
                    yield f"{language}:{case['Index']}:{variant}", {
                        "case": case, "language": language, "category": category, "variant": variant, "entry": entry}


# ---- rules ---------------------------------------------------------------------------------
@RULES.rule("rc.category")
def category(item, rec: Record) -> bool:
    """rc.category: the risk category's decision and modes; the user is the source of the harm.

    Args:
        item: The source item.
        rec: The Record being built.

    Returns:
        True (every kept item is in the table).
    """
    entry = item["entry"]
    rec.set("decision", entry["decision"], "rule_inferred", "rc.category")
    rec.add_modes(["principal_misuse"] + list(entry.get("modes") or []), "rule_inferred", "rc.category")
    rec.set("attack_vector", "none", "rule_inferred", "rc.category")
    rec.set("action_relation", "harmful_user_task", "rule_inferred", "rc.category")
    rec.set("adversarial_locations", [], "rule_inferred", "rc.category")
    rec.set("hard_negative", False, "rule_inferred", "rc.category")
    return True


# ---- record --------------------------------------------------------------------------------
def to_record(original_id: str, item: dict, revision: str) -> tuple[str, Record]:
    """Convert one case and request variant into a step Record.

    Args:
        original_id: "<language>:<Index>:<variant>".
        item: The source item.
        revision: The snapshot's commit.

    Returns:
        `(record_id, record)`: "redcode:" + original_id and the Record.
    """
    case, language = item["case"], item["language"]
    case_key = f"{language}:{case['Index']}"
    tool = host_tool(language, case_key)
    request = case[VARIANT_FIELD[item["variant"]]]
    rec = Record(DATASET, original_id, "step")
    rec.input = {"system_prompt": None, "user_prompt": request,
                 "messages": [{"role": "user", "content": request, "trust": "principal"}],
                 "tools_available": [{"name": tool["name"], "description": tool["description"],
                                      "parameters_schema": tool["parameters_schema"], "origin": "mcp",
                                      "side_effects": "code_exec"}],
                 "planned_action": {"tool_name": tool["name"], "arguments": {tool["argument"]: case["Code"]},
                                    "reasoning": None},
                 "principal": None, "modality": "text"}
    rec.source.update({
        "dataset_version": revision, "original_split": None, "step_index": 1, "generator_model": None,
        "license": "CC BY 4.0 (RedCode, AI-secure); host tool specs from TOUCAN (Apache-2.0)",
        "original_label": {"category": item["category"], "category_name": item["entry"]["name"], "language": language,
                           "variant": item["variant"], "expected_result": case.get("expected_result"),
                           "host_tool": tool["name"]},
    })
    rec.source["group_ids"] = {"task": f"redcode:{case_key}", "attack": f"redcode:category:{item['category']}",
                               "trajectory": f"redcode:{case_key}", "author": "redcode:benchmark_authors"}
    RULES.apply(item, rec)
    return f"redcode:{original_id}", rec


# ---- dataset-specific report section ---------------------------------------------------------
EXPECTED = {"cases_bash": 600, "cases_python": 810}


def report_extras(records: list[dict]) -> dict:
    """Build the RedCode section of report.json.

    Args:
        records: The valid converted records.

    Returns:
        Reconciliation of case counts, cases excluded as code quality, and records by category,
        language, decision and host tool.
    """
    ol = lambda r: r["source"]["original_label"]  # noqa: E731
    return {
        "reconciliation": {k: {"expected": v, "measured": STATS[k], "ok": STATS[k] == v} for k, v in EXPECTED.items()},
        "funnel": dict(sorted(STATS.items())),
        "by_category": dict(sorted(Counter(f'{ol(r)["category"]:02d} {ol(r)["category_name"]}' for r in records).items())),
        "by_language": dict(Counter(ol(r)["language"] for r in records)),
        "by_decision": dict(Counter(r["labels"]["decision"] for r in records)),
        "by_host_tool": dict(Counter(ol(r)["host_tool"] for r in records)),
    }
