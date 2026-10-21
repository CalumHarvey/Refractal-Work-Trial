"""Human review of generated groups: sheets, import, the MVP gates and calibration entries.

Gate 1 (pilot): every pilot group is checked. Passes with >= 90% correct decisions over all three
branches, 100% of BLOCKs with their cause visible in the input, and a yield >= 20%.
Gate 2 (scale): a random sample of kept groups; passes with >= 90% correct decisions.
The audited precision per rule is printed as a `calibration.rules` entry for
label-schema/dataset_mappings.yaml.
"""
import csv
import json
import math
from collections import Counter
from datetime import date

from ingest.common.text import sha1_12

from .inject import DATASET, operator_of
from .run_folders import read_jsonl, run_dir, write_jsonl

FIELDS = ["group_id", "side", "operator", "attack_dataset", "user_request", "injection_text", "block_call",
          "aware_call", "benign_request", "benign_call", "judge_total",
          "block_correct", "cause_visible", "aware_correct", "benign_correct", "notes"]
RULE_OF_FIELD = {"block_correct": "gi.block", "aware_correct": "gi.aware_allow", "benign_correct": "gi.benign_reuse"}


def write_sheet(run_id: str, sample: int | None = None, include_rejected: bool = False) -> dict:
    """Write an audit sheet of generated groups.

    Reviewers fill `block_correct`, `cause_visible`, `aware_correct`, `benign_correct` with y / n.
    Full context for each group is in review_groups.md next to the sheet.

    Args:
        run_id: The gen_inject run folder.
        sample: Check a random sample of this many kept groups (Gate 2); None checks every group
            (Gate 1, pilot).
        include_rejected: Also list rejected groups (to audit the filter itself).

    Returns:
        `{"path": ..., "groups": n}`.
    """
    folder = run_dir(DATASET, run_id)
    rows = [r for r in read_jsonl(folder / "groups.jsonl") if r["status"] == "kept" or include_rejected]
    if sample is not None:
        rows = sorted(rows, key=lambda r: sha1_12("audit|" + r["group_id"]))[:sample]
    path = folder / ("review_sample.csv" if sample is not None else "review_all.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for r in rows:
            gen = (r["generator"].get("output") or {})
            writer.writerow({
                "group_id": r["group_id"], "side": r["side"], "operator": operator_of(gen, r),
                "attack_dataset": r["attack"]["dataset"], "user_request": r["context"]["user_prompt"],
                "injection_text": gen.get("injection_text"),
                "block_call": json.dumps(gen.get("attacker_action"), ensure_ascii=False),
                "aware_call": json.dumps({k: r["context"]["planned_action"][k] for k in ("tool_name", "arguments")}, ensure_ascii=False),
                "benign_request": (gen.get("benign_reuse") or {}).get("user_request"),
                "benign_call": json.dumps((gen.get("benign_reuse") or {}).get("action"), ensure_ascii=False),
                "judge_total": sum(v for v in (r["judge"].get("scores") or {}).values() if isinstance(v, int)),
                "block_correct": "", "cause_visible": "", "aware_correct": "", "benign_correct": "", "notes": ""})
    (folder / "review_groups.md").write_text("\n\n".join(
        f"## {r['group_id']} ({r['status']})\n\n**User:** {r['context']['user_prompt']}\n\n"
        f"**Injected tool output:**\n```\n{(r['generator'].get('output') or {}).get('injected_tool_output', '')[:6000]}\n```\n\n"
        f"**Generator output:**\n```json\n{json.dumps(r['generator'].get('output'), indent=2, ensure_ascii=False)[:6000]}\n```"
        for r in rows), encoding="utf-8")
    return {"path": str(path), "groups": len(rows)}


def import_sheet(run_id: str, sheet: str) -> dict:
    """Import a filled review sheet into review.jsonl (one row per group, answers as booleans).

    Args:
        run_id: The gen_inject run folder.
        sheet: Path of the filled CSV.

    Returns:
        `{"groups": n, "unanswered": n}`.
    """
    folder = run_dir(DATASET, run_id)
    out, unanswered = [], 0
    with open(sheet, newline="", encoding="utf-8") as f:
        for line in csv.DictReader(f):
            answers = {}
            for field in ("block_correct", "cause_visible", "aware_correct", "benign_correct"):
                value = (line.get(field) or "").strip().lower()
                answers[field] = True if value in ("y", "yes", "1", "true") else False if value in ("n", "no", "0", "false") else None
            unanswered += any(v is None for v in answers.values())
            out.append({"group_id": line["group_id"], **answers, "notes": line.get("notes") or ""})
    previous = {r["group_id"]: r for r in read_jsonl(folder / "review.jsonl")}
    previous.update({r["group_id"]: r for r in out})
    write_jsonl(folder / "review.jsonl", list(previous.values()))
    return {"groups": len(out), "unanswered": unanswered}


def _interval(k: int, n: int) -> list[float]:
    """Wilson 95% interval for a proportion.

    Args:
        k: Successes.
        n: Trials.

    Returns:
        `[low, high]`, rounded to 3 places.
    """
    if not n:
        return [0.0, 0.0]
    z, p = 1.96, k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(centre - half, 3), round(centre + half, 3)]


def gate(run_id: str) -> dict:
    """Compute Gate 1 / Gate 2 figures and calibration entries from the audit.

    Args:
        run_id: The gen_inject run folder.

    Returns:
        Audited groups, correct-decision share over all answered branches, cause-visible share on
        BLOCKs, yield, pass flags, and a `calibration` block per rule (precision, n, Wilson CI).
    """
    folder = run_dir(DATASET, run_id)
    groups = {g["group_id"]: g for g in read_jsonl(folder / "groups.jsonl")}
    audit = [a for a in read_jsonl(folder / "review.jsonl") if a["group_id"] in groups]
    branch = [a[f] for a in audit for f in RULE_OF_FIELD if a[f] is not None]
    visible = [a["cause_visible"] for a in audit if a["cause_visible"] is not None]
    kept = sum(g["status"] == "kept" for g in groups.values())
    correct = sum(branch) / len(branch) if branch else None
    calibration = {}
    for field, rule in RULE_OF_FIELD.items():
        answers = [a[field] for a in audit if a[field] is not None]
        if answers:
            calibration[rule] = {"decision": {"status": "audited", "precision": round(sum(answers) / len(answers), 3),
                                              "n": len(answers), "ci95": _interval(sum(answers), len(answers)),
                                              "audited_on": date.today().isoformat()}}
    return {"audited_groups": len(audit), "correct_decisions": correct,
            "cause_visible": sum(visible) / len(visible) if visible else None,
            "yield": kept / len(groups) if groups else None,
            "gate1_passes": bool(correct is not None and correct >= 0.9 and visible and all(visible)
                                 and groups and kept / len(groups) >= 0.2),
            "gate2_passes": bool(correct is not None and correct >= 0.9),
            "calibration": calibration,
            "rejected_reasons": dict(Counter(r for g in groups.values() if g["status"] != "kept" for r in g["reasons"]))}
