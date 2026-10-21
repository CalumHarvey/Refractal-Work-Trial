"""Seed libraries: the real pieces generation composes, split by side before anything is generated.

Two sides:
- train: seeds whose real data is on the train side of the split plan (TOUCAN train-split contexts,
  InjecAgent attacker instructions on grid side A, LLMail-Inject phase 1). Generated records built
  from them follow them into train.
- diagnostic: seeds from held-out data (TOUCAN test-split contexts, InjecAgent grid side B, LLMail
  phase 2). Records built from them form the Tier 3 diagnostic split and are never trained on.

Only licensed datasets are read (the licence gate in config/build.yaml). Libraries are written to
data/generated/libraries/<side>/{contexts,attacks}.jsonl with a manifest of hashes, which every
generation run records.
"""
import json
from collections import Counter, defaultdict

from ingest.assembly.config import build_config
from ingest.assembly.split_plan import load_plan
from ingest.assembly.split import grid_side
from ingest.common.paths import GENERATED, PROCESSED, raw_snapshot
from ingest.common.text import normalise, sha1_12
from ingest.convert.injecagent import match_key

from .config import generation_config
from .run_folders import file_sha, write_jsonl

LIBRARY_DIR = GENERATED / "libraries"
SIDE_SPLITS = {"train": {"train"}, "diagnostic": {"test"}}   # plan splits each side draws contexts from
SIDE_GRID = {"train": "A", "diagnostic": "B"}
SIDE_PHASE = {"train": 1, "diagnostic": 2}
NON_SIDE_EFFECTS = ("read_only", "unknown", None)


def _order(text: str) -> str:
    """Give a stable pseudo-random sort key.

    Args:
        text: Any identifier.

    Returns:
        Its sha1 prefix.
    """
    return sha1_12("library|" + text)


# ---- contexts ------------------------------------------------------------------------------
def context_from_record(rec: dict) -> dict | None:
    """Turn a processed TOUCAN record into a context seed, if it can host an injection.

    A context needs a tool output as its last message (the injection is planted there), a planned
    tool call (not a final answer: it becomes the aware-ALLOW branch), and at least one tool with
    side effects (the attacker's call needs something to abuse).

    Args:
        rec: A processed TOUCAN record.

    Returns:
        The context seed, or None if the record cannot host an injection.
    """
    cfg = generation_config()["libraries"]["contexts"]
    inp = rec["input"]
    messages = inp["messages"]
    if cfg["require_tool_output"] and (not messages or messages[-1]["role"] != "tool" or not messages[-1]["content"].strip()):
        return None
    if inp["planned_action"]["tool_name"] == "final_answer":
        return None
    effectful = [t["name"] for t in inp["tools_available"] if t.get("side_effects") not in NON_SIDE_EFFECTS]
    if cfg["require_side_effect_tool"] and not effectful:
        return None
    return {"record_id": rec["record_id"], "dataset": rec["source"]["dataset"],
            "task_key": rec["source"]["group_ids"]["task"], "trajectory_key": rec["source"]["group_ids"]["trajectory"],
            "user_prompt": inp.get("user_prompt"), "messages": messages, "tools": inp["tools_available"],
            "planned_action": inp["planned_action"], "side_effect_tools": effectful,
            "servers": (rec["source"].get("original_label") or {}).get("servers")}


def contexts(side: str, plan: dict[str, str]) -> list[dict]:
    """Collect context seeds for one side.

    At most one context per TOUCAN run (so one run's prefix is not reused across groups), in a
    stable pseudo-random order, capped at `max_contexts`.

    Args:
        side: "train" or "diagnostic".
        plan: The split plan, `{record_id: split}`.

    Returns:
        Context seeds.
    """
    cfg = generation_config()["libraries"]["contexts"]
    path = PROCESSED / cfg["source"] / "records.jsonl"
    out, seen_runs = [], set()
    with open(path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f]
    for rec in sorted(records, key=lambda r: _order(r["record_id"])):
        if plan.get(rec["record_id"]) not in SIDE_SPLITS[side]:
            continue
        ctx = context_from_record(rec)
        if ctx is None or ctx["trajectory_key"] in seen_runs:
            continue
        seen_runs.add(ctx["trajectory_key"])
        out.append(ctx)
        if len(out) >= cfg["max_contexts"]:
            break
    return out


# ---- attacks -------------------------------------------------------------------------------
def injecagent_attacks(side: str) -> list[dict]:
    """Collect InjecAgent attacker instructions on one side of its grid split.

    Args:
        side: "train" (grid side A) or "diagnostic" (grid side B).

    Returns:
        Attack seeds with the same `injecagent:attack:<hash>` key the converter writes, so the
        build resolves their side the same way.
    """
    b_share = build_config()["sources"]["injecagent"]["grid"]["b_share"]
    cap = generation_config()["libraries"]["attacks"]["injecagent"]["max"]
    out = []
    for kind in ("dh", "ds"):
        path = raw_snapshot("injecagent") / "data" / f"attacker_cases_{kind}.jsonl"
        with open(path, encoding="utf-8") as f:
            for line in f:
                case = json.loads(line)
                key = f"injecagent:attack:{sha1_12(match_key(case['Attacker Instruction']))}"
                if grid_side(key, b_share) != SIDE_GRID[side]:
                    continue
                out.append({"dataset": "injecagent", "key": key, "kind": kind, "text": case["Attacker Instruction"],
                            "goal": case["Expected Achievements"], "attack_type": case["Attack Type"],
                            "attacker_tools": case["Attacker Tools"]})
    return sorted(out, key=lambda a: _order(a["key"]))[:cap]


def llmail_attacks(side: str) -> list[dict]:
    """Collect unique LLMail-Inject emails whose unauthorised send reached the attacker.

    Phase 1 feeds the train side and phase 2 the diagnostic side (a time-based split). Emails are
    kept if the send happened to the right destination, deduplicated on normalised text, capped
    per team (so one team's variants do not dominate) and overall.

    Args:
        side: "train" (phase 1) or "diagnostic" (phase 2).

    Returns:
        Attack seeds with keys `llmail_inject:phase<n>:<hash>` (see config `seed_splits`).
    """
    cfg = generation_config()["libraries"]["attacks"]["llmail_inject"]
    phase = SIDE_PHASE[side]
    path = raw_snapshot("llmail_inject") / "data" / f"raw_submissions_phase{phase}.jsonl"
    by_key, per_team = {}, Counter()
    with open(path, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            try:
                objectives = json.loads(row.get("objectives") or "{}")
            except (TypeError, ValueError):
                continue
            if not (objectives.get("exfil.sent") and objectives.get("exfil.destination")):
                continue
            text = f"Subject: {row.get('subject') or ''}\n\n{row.get('body') or ''}".strip()
            if not cfg["min_chars"] <= len(text) <= cfg["max_chars"]:
                continue
            key = f"llmail_inject:phase{phase}:{sha1_12(normalise(text))}"
            if key not in by_key:
                by_key[key] = {"dataset": "llmail_inject", "key": key, "kind": "email", "text": text,
                               "goal": "Make the assistant send an email to an address the attacker chose.",
                               "attack_type": "Data exfiltration / unauthorised send", "team": row.get("team_id"),
                               "attacker_tools": ["send_email"]}
    out = []
    per_team_cap = max(1, cfg["max_per_phase"] // 50)
    for attack in sorted(by_key.values(), key=lambda a: _order(a["key"])):
        if per_team[attack["team"]] >= per_team_cap:
            continue
        per_team[attack["team"]] += 1
        out.append(attack)
        if len(out) >= cfg["max_per_phase"]:
            break
    return out


# ---- build and load ------------------------------------------------------------------------
def build(sides: tuple[str, ...] = ("train", "diagnostic")) -> dict:
    """Build the seed libraries for the given sides from the split plan.

    Args:
        sides: Which sides to build.

    Returns:
        `{side: {"contexts": n, "attacks": {dataset: n}, "sha": {...}}}`, also written to
        data/generated/libraries/manifest.json.

    Raises:
        FileNotFoundError: If there is no split plan (run ingest/build.py --plan-splits).
    """
    plan = load_plan()
    summary = {}
    for side in sides:
        folder = LIBRARY_DIR / side
        folder.mkdir(parents=True, exist_ok=True)
        ctx = contexts(side, plan)
        attacks = injecagent_attacks(side) + llmail_attacks(side)
        summary[side] = {"contexts": len(ctx), "attacks": dict(Counter(a["dataset"] for a in attacks)),
                         "sha": {"contexts": write_jsonl(folder / "contexts.jsonl", ctx),
                                 "attacks": write_jsonl(folder / "attacks.jsonl", attacks)}}
    (LIBRARY_DIR / "manifest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def load(side: str) -> tuple[list[dict], dict[str, list[dict]], dict]:
    """Load one side's libraries.

    Args:
        side: "train" or "diagnostic".

    Returns:
        `(contexts, attacks by dataset, hashes)`.

    Raises:
        FileNotFoundError: If the libraries have not been built (`python -m generate libraries`).
    """
    folder = LIBRARY_DIR / side
    if not (folder / "contexts.jsonl").exists():
        raise FileNotFoundError(f"no {side} libraries in {folder}; run: python -m generate libraries")
    with open(folder / "contexts.jsonl", encoding="utf-8") as f:
        ctx = [json.loads(line) for line in f]
    attacks = defaultdict(list)
    with open(folder / "attacks.jsonl", encoding="utf-8") as f:
        for line in f:
            a = json.loads(line)
            attacks[a["dataset"]].append(a)
    hashes = {"contexts": file_sha(folder / "contexts.jsonl"), "attacks": file_sha(folder / "attacks.jsonl")}
    return ctx, dict(attacks), hashes
