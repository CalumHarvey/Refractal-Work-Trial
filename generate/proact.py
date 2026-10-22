"""PROACT-style unrolling of ATBench: locate the first unsafe planned action of each unsafe run.

For every ATBench run this writes one row to data/derived/atbench_steps/<run>/boundaries.jsonl
(relabelled real data: the content is ATBench's own, only the step labels are new):
- safe runs (label 0): no boundary needed; every step is ALLOW.
- unsafe runs: the boundary is located by a rule when it is unambiguous (the run has a single agent
  action, or a single action after the planted content), otherwise by the configured Gemini judges,
  which must agree (`min_agreeing_judges`). Judges answering "no single boundary" (omissions, diffuse
  failures) leave the run without step records; disagreement leaves it unresolved.

The converter ingest/convert/atbench_steps.py turns the rows into step records. A human check sheet
(CSV) covers every test-side boundary and a random train-side sample; filled sheets are imported to
human.jsonl, which overrides the located boundary (rule as.boundary_human).
"""
import csv
import json
import logging
import time
from collections import Counter

from ingest.assembly.split_plan import load_plan
from ingest.common.paths import raw_snapshot
from ingest.common.text import sha1_12
from ingest.convert import atbench

from . import llm
from .config import generation_config
from .prompts import BOUNDARY_PROMPT, BOUNDARY_SYSTEM, BOUNDARY_VERSION
from .logs import run_log
from .run_folders import read_jsonl, run_dir, write_jsonl, write_manifest

DATASET = "atbench_steps"
log = logging.getLogger("generate.proact")
MAX_OUTPUT_CHARS = 1500


def decision_points(messages: list[dict]) -> list[int]:
    """Find the agent actions a guard decides on.

    Args:
        messages: A run's schema messages (from atbench.build_input).

    Returns:
        Indexes of assistant messages: tool calls, and final answers (assistant text without a call).
    """
    return [i for i, m in enumerate(messages)
            if m["role"] == "assistant" and (m.get("tool_call") or (m.get("content") or "").strip())]


def planned_action(message: dict) -> dict:
    """The planned action a decision point represents.

    Args:
        message: An assistant message.

    Returns:
        Its tool call, or a final_answer pseudo-call ({"text": ...}) for a final answer.
    """
    if message.get("tool_call"):
        return message["tool_call"]
    return {"tool_name": "final_answer", "arguments": {"text": message.get("content") or ""}, "reasoning": None}


def transcript(messages: list[dict], points: list[int]) -> str:
    """Render a run for the judges, numbering the agent actions.

    Args:
        messages: The run's schema messages.
        points: Indexes of the decision points.

    Returns:
        A readable transcript; tool outputs are shortened to MAX_OUTPUT_CHARS.
    """
    number = {idx: n + 1 for n, idx in enumerate(points)}
    lines = []
    for i, m in enumerate(messages):
        if i in number:
            call = planned_action(m)
            thought = f" (thought: {m['content'][:400]})" if m.get("tool_call") and m.get("content") else ""
            lines.append(f"[A{number[i]}] AGENT ACTION: {json.dumps(call, ensure_ascii=False)[:1500]}{thought}")
        elif m["role"] == "user":
            lines.append(f"USER: {m['content']}")
        elif m["role"] == "tool":
            content = m["content"] if len(m["content"]) <= MAX_OUTPUT_CHARS else m["content"][:MAX_OUTPUT_CHARS] + " ...[shortened]"
            lines.append(f"TOOL OUTPUT ({m.get('tool_name')}): {content}")
        else:
            lines.append(f"AGENT: {(m.get('content') or '')[:600]}")
    return "\n".join(lines)


def rule_boundary(points: list[int], marked: list[int]) -> tuple[int | None, str | None]:
    """Locate a boundary without a model, when the run leaves no choice.

    Args:
        points: Indexes of the decision points.
        marked: Indexes of messages that carried ATBench's planting markers.

    Returns:
        `(message index, reason)`, or `(None, None)` when a judge is needed.
    """
    if len(points) == 1:
        return points[0], "single agent action"
    if marked:
        after = [p for p in points if p > marked[0]]
        if len(after) == 1:
            return after[0], "single agent action after the planted content"
    return None, None


def judge_boundary(run: dict, messages: list[dict], points: list[int]) -> dict:
    """Ask every configured judge for the boundary and combine their answers.

    Args:
        run: The raw ATBench run.
        messages: Its schema messages.
        points: Indexes of the decision points.

    Returns:
        `{"boundary": message index | None, "method": "judges" | "no_single" | "unresolved" | "error",
        "judges": {model: answer}}`. "error" (a judge failed and the others did not agree) is
        retried when the run is resumed.

    Raises:
        llm.QuotaExhausted: If a daily quota runs out (the run can be resumed).
    """
    tools = "\n".join(f"- {t['name']}: {(t.get('description') or '')[:200]}" for t in run["tool_used"])
    prompt = BOUNDARY_PROMPT.format(risk_source=run["risk_source"], failure_mode=run["failure_mode"],
                                    reason=run.get("reason") or "", tools=tools,
                                    transcript=transcript(messages, points))
    models = generation_config()["models"]
    judges = models["boundary_judges"]
    # one model listed several times = independent samples of it (self-consistency), so sample > 0
    temperature = models.get("boundary_temperature", 0.7) if len(set(judges)) < len(judges) else 0.0
    answers = {}
    for index, model in enumerate(judges):
        label = f"{model}#{index}" if judges.count(model) > 1 else model
        try:
            reply = llm.generate_json(model, prompt, datasets=["atbench"], system=BOUNDARY_SYSTEM,
                                      temperature=temperature, sample=index if judges.count(model) > 1 else 0)
            value = reply["value"] if isinstance(reply["value"], dict) else {}
            step = value.get("step")
            answers[label] = {"step": step if isinstance(step, int) and 1 <= step <= len(points) else None,
                              "single_boundary": bool(value.get("single_boundary")),
                              "rationale": str(value.get("rationale") or "")[:500],
                              "model_used": reply["model"], "model_version": reply["model_version"]}
        except llm.LLMError as exc:
            answers[label] = {"step": None, "single_boundary": None, "error": str(exc)[:300]}
    need = generation_config()["proact"]["min_agreeing_judges"]
    # one vote per judgement: a judge whose model fell back to the same model as another judge's (and is
    # not a deliberate sample of it) counts once
    distinct = {(a.get("model_used"), label if "#" in label else None): a
                for label, a in answers.items() if "error" not in a}.values()
    votes = Counter(a["step"] for a in distinct if a.get("single_boundary") and a["step"])
    if votes and votes.most_common(1)[0][1] >= need:
        return {"boundary": points[votes.most_common(1)[0][0] - 1], "method": "judges", "judges": answers}
    if any("error" in a for a in answers.values()):
        return {"boundary": None, "method": "error", "judges": answers}  # retried on the next run
    if sum(a.get("single_boundary") is False for a in distinct) >= need:
        return {"boundary": None, "method": "no_single", "judges": answers}
    return {"boundary": None, "method": "unresolved", "judges": answers}


def locate(run_id: str, limit: int | None = None, split: str | None = None) -> dict:
    """Locate boundaries for every ATBench run and write the run folder.

    Resumable: runs already in boundaries.jsonl are skipped, except those whose judges failed
    (method "error"); judge replies are cached, so only failed calls are repeated.

    Args:
        run_id: Name of the run folder, e.g. "proact-v1".
        limit: Process at most this many new unsafe runs that need judges (for a pilot).
        split: Judge only runs on this split of the plan ("train" or "test"); runs that need no
            judges are located on every split. None judges every split.

    Returns:
        Counts by method and split, also written to the manifest.
    """
    folder = run_dir(DATASET, run_id)
    path = folder / "boundaries.jsonl"
    done = {row["run_id"]: row for row in read_jsonl(path)}
    plan = load_plan()
    snapshot = raw_snapshot("atbench")
    judged, stopped = 0, None
    with run_log(folder) as log_path:
        log.info("PROACT run %s: %d runs already located; judging %s%s; log file %s", run_id, len(done),
                 "all remaining" if limit is None else f"at most {limit}", f" on the {split} split" if split else "", log_path)
        started = time.monotonic()
        try:
            for original_id, run in atbench.iter_source(snapshot):
                if original_id in done and done[original_id]["method"] != "error":
                    continue
                messages, marked = atbench.build_input(run)
                points = decision_points(messages["messages"])
                row = {"run_id": original_id, "label": run["label"], "split": plan.get(f"atbench:{original_id}"),
                       "decision_points": points, "marked": marked, "boundary": None, "method": None,
                       "rule_reason": None, "judges": {}}
                if run["label"] == 0:
                    row["method"] = "safe"
                elif not points:
                    row["method"] = "no_actions"
                else:
                    boundary, reason = rule_boundary(points, marked)
                    if boundary is not None:
                        row.update(boundary=boundary, method="marker", rule_reason=reason)
                    else:
                        if (limit is not None and judged >= limit) or (split and row["split"] != split):
                            continue
                        t0 = time.monotonic()
                        row.update(judge_boundary(run, messages["messages"], points))
                        judged += 1
                        votes = [a.get("step") for a in row["judges"].values()]
                        log.info("run %s (%s): %s%s  votes %s  %.1fs", original_id, row["split"], row["method"],
                                 f" at action {points.index(row['boundary']) + 1}" if row["boundary"] is not None else "",
                                 votes, time.monotonic() - t0)
                        if judged % 10 == 0:
                            per = (time.monotonic() - started) / judged
                            log.info("progress: %d runs judged, %.1fs per run", judged, per)
                done[original_id] = row
                if len(done) % 25 == 0:
                    write_jsonl(path, list(done.values()))
        except llm.QuotaExhausted as exc:
            stopped = str(exc)
            log.warning("stopped on a daily quota after judging %d runs; run the same command later to resume", judged)
        write_jsonl(path, list(done.values()))
        counts = {"by_method": dict(Counter(r["method"] for r in done.values())),
                  "by_split_and_method": dict(Counter(f"{r['split']}:{r['method']}" for r in done.values())),
                  "runs": len(done)}
        log.info("done: %d judged now; run total %d, by method %s", judged, len(done), counts["by_method"])
    write_manifest(folder, DATASET, run_id, "boundaries.jsonl", {
        "parents": {"atbench": json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))["revision"]},
        "models": generation_config()["models"]["boundary_judges"],
        "boundary_temperature": generation_config()["models"].get("boundary_temperature"), "prompt_version": BOUNDARY_VERSION,
        "min_agreeing_judges": generation_config()["proact"]["min_agreeing_judges"],
        "counts": counts, "stopped": stopped})
    return {**counts, "stopped": stopped}


# ---- human check -----------------------------------------------------------------------------
SHEET_FIELDS = ["run_id", "split", "method", "proposed_action_number", "proposed_action", "atbench_reason",
                "judge_rationales", "human_action_number", "human_no_single_boundary", "notes"]


def write_sheet(run_id: str) -> dict:
    """Write the human check sheet: every test-side boundary and a random train-side sample.

    Columns `human_action_number` (the correct first unsafe action, if different), and
    `human_no_single_boundary` ("yes" if no single action should have been blocked) are for the
    reviewer; leave both blank to confirm the proposed boundary.

    Args:
        run_id: The PROACT run folder.

    Returns:
        `{"path": ..., "test": n, "train": n}`.
    """
    folder = run_dir(DATASET, run_id)
    rows = [r for r in read_jsonl(folder / "boundaries.jsonl") if r["method"] in ("marker", "judges")]
    raw = dict(atbench.iter_source(raw_snapshot("atbench")))
    cfg = generation_config()["proact"]["human_sample"]
    test = [r for r in rows if r["split"] == "test"]
    train = sorted((r for r in rows if r["split"] == "train"), key=lambda r: sha1_12("sheet|" + r["run_id"]))[:cfg["train"]]
    path = folder / "human_check.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SHEET_FIELDS)
        writer.writeheader()
        for r in test + train:
            messages, _ = atbench.build_input(raw[r["run_id"]])
            number = r["decision_points"].index(r["boundary"]) + 1
            writer.writerow({"run_id": r["run_id"], "split": r["split"], "method": r["method"],
                             "proposed_action_number": number,
                             "proposed_action": json.dumps(planned_action(messages["messages"][r["boundary"]]), ensure_ascii=False)[:800],
                             "atbench_reason": raw[r["run_id"]].get("reason"),
                             "judge_rationales": " | ".join(f"{m}: {a.get('rationale', '')}" for m, a in r["judges"].items()),
                             "human_action_number": "", "human_no_single_boundary": "", "notes": ""})
    (folder / "human_check_transcripts.md").write_text("\n\n".join(
        f"## Run {r['run_id']} ({r['split']})\n\n```\n{transcript(atbench.build_input(raw[r['run_id']])[0]['messages'], r['decision_points'])}\n```"
        for r in test + train), encoding="utf-8")
    return {"path": str(path), "test": len(test), "train": len(train)}


def import_sheet(run_id: str, sheet: str | None = None) -> dict:
    """Import a filled human check sheet into human.jsonl.

    Args:
        run_id: The PROACT run folder.
        sheet: Path of the filled CSV; defaults to the run's human_check.csv.

    Returns:
        `{"reviewed": n, "confirmed": n, "corrected": n, "no_single": n}`.

    Raises:
        ValueError: If a human action number is outside the run's actions.
    """
    folder = run_dir(DATASET, run_id)
    rows = {r["run_id"]: r for r in read_jsonl(folder / "boundaries.jsonl")}
    out, stats = [], Counter()
    with open(sheet or folder / "human_check.csv", newline="", encoding="utf-8") as f:
        for line in csv.DictReader(f):
            row = rows[line["run_id"]]
            if (line.get("human_no_single_boundary") or "").strip().lower() in ("yes", "y", "true", "1"):
                out.append({"run_id": line["run_id"], "boundary": None, "no_single_boundary": True})
                stats["no_single"] += 1
                continue
            number = (line.get("human_action_number") or "").strip()
            if number:
                n = int(number)
                if not 1 <= n <= len(row["decision_points"]):
                    raise ValueError(f"run {line['run_id']}: action {n} out of range")
                boundary = row["decision_points"][n - 1]
                stats["corrected" if boundary != row["boundary"] else "confirmed"] += 1
            else:
                boundary = row["boundary"]
                stats["confirmed"] += 1
            out.append({"run_id": line["run_id"], "boundary": boundary, "no_single_boundary": False})
    write_jsonl(folder / "human.jsonl", out)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    write_manifest(folder, DATASET, run_id, "boundaries.jsonl",
                   {k: v for k, v in manifest.items() if k not in ("dataset", "run", "revision", "updated_at", "folder", "files")})
    return {"reviewed": len(out), **stats}


def gate(run_id: str) -> dict:
    """Gate P: agreement between located boundaries and the human check on the train sample.

    Args:
        run_id: The PROACT run folder.

    Returns:
        `{"train_checked": n, "agreement": share, "passes": bool, "threshold": 0.85}`.
    """
    folder = run_dir(DATASET, run_id)
    rows = {r["run_id"]: r for r in read_jsonl(folder / "boundaries.jsonl")}
    human = [h for h in read_jsonl(folder / "human.jsonl") if rows[h["run_id"]]["split"] == "train"]
    agree = sum((not h["no_single_boundary"]) and h["boundary"] == rows[h["run_id"]]["boundary"] for h in human)
    share = agree / len(human) if human else None
    return {"train_checked": len(human), "agreement": share, "threshold": 0.85,
            "passes": share is not None and share >= 0.85}
