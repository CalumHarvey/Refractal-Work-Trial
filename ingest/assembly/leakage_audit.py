"""Leakage and shortcut audit of a finished split (written to report.json under "audit").

Group keys keep related records apart by construction (`split.leakage`); this checks the content
itself, which keys can miss:
- overlap: evaluation records whose instruction, history, planned action or injected tool output
  also occurs (normalised) in train, plus near-duplicate instructions under different keys;
- shortcuts: how well the planned tool's name alone predicts the decision, per source;
- markers: dataset names and generator markers in the Jev events (which must be source-blind).
Anything suspicious becomes a line in "warnings", which build.py prints.
"""
import json
import re
from collections import Counter, defaultdict

from ..common.text import normalise
from .config import build_config, source_key

EVAL_SPLITS = ("validation", "test", "holdout")
NEAR_DUP_JACCARD = 0.7
SHORTCUT_MARGIN = 0.15


def _h(value) -> str:
    """Canonical string of a value, for exact-match indexes.

    Args:
        value: Any JSON value.

    Returns:
        Sorted-key JSON of the value; strings are normalised first.
    """
    if isinstance(value, str):
        return normalise(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _instruction(rec: dict) -> str:
    """The record's first user turn.

    Args:
        rec: A record.

    Returns:
        Its content, or "" when there is none.
    """
    return next((m["content"] or "" for m in rec["input"]["messages"] if m["role"] == "user"), "")


def _injected(rec: dict) -> list[str]:
    """Tool outputs / messages labelled as holding an attack.

    Args:
        rec: A record.

    Returns:
        The contents of messages named by its adversarial_locations.
    """
    msgs = rec["input"]["messages"]
    return [msgs[loc["message_index"]]["content"] or "" for loc in rec["labels"]["adversarial_locations"] or []
            if loc["kind"] == "message" and loc.get("message_index") is not None and loc["message_index"] < len(msgs)]


FEATURES = {
    "instruction": lambda r: [_h(_instruction(r))],
    "history": lambda r: [_h(r["input"]["messages"])] if len(r["input"]["messages"]) > 1 else [],
    "planned_action": lambda r: [_h({k: r["input"]["planned_action"][k] for k in ("tool_name", "arguments")})]
    if r["input"]["planned_action"] else [],
    "injected_content": lambda r: [_h(t) for t in _injected(r) if len(normalise(t)) > 20],
}


def overlap(records: list[dict], splits: dict[str, str]) -> dict:
    """Count evaluation records that share content with train.

    Args:
        records: All records.
        splits: `{record_id: split}`.

    Returns:
        `{feature: {split: {source: "hits/total"}}}` for each FEATURES entry, plus
        "near_duplicate_instruction" (word 5-gram Jaccard >= NEAR_DUP_JACCARD with a train record)
        and `_hits` (`{feature: {split: n}}`) for the warnings.
    """
    train = [r for r in records if splits[r["record_id"]] == "train"]
    out, hits = {}, defaultdict(dict)
    for name, fn in FEATURES.items():
        seen = {k for r in train for k in fn(r)}
        out[name] = {}
        for split_name in EVAL_SPLITS:
            tally = defaultdict(lambda: [0, 0])
            for r in records:
                if splits[r["record_id"]] == split_name:
                    t = tally[source_key(r)]
                    t[0] += any(k in seen for k in fn(r))
                    t[1] += 1
            out[name][split_name] = {s: f"{a}/{b}" for s, (a, b) in sorted(tally.items())}
            hits[name][split_name] = sum(a for a, _ in tally.values())
    out["near_duplicate_instruction"], hits["near_duplicate_instruction"] = _near_duplicates(records, splits, train)
    out["_hits"] = dict(hits)
    return out


def _grams(text: str, n: int = 5) -> set[str]:
    """Word n-grams of a normalised text.

    Args:
        text: Any text.
        n: Gram length.

    Returns:
        The set of n-grams (one gram for shorter texts).
    """
    words = normalise(text).split()
    return {" ".join(words[i:i + n]) for i in range(max(1, len(words) - n + 1))}


def _near_duplicates(records, splits, train) -> tuple[dict, dict]:
    """Find evaluation instructions that nearly match a train instruction.

    Args:
        records: All records.
        splits: `{record_id: split}`.
        train: The train records.

    Returns:
        `({split: {"count": n, "examples": [...]}}, {split: n})`.
    """
    train_grams = [_grams(_instruction(r)) for r in train]
    index = defaultdict(list)
    for i, g in enumerate(train_grams):
        for gram in g:
            index[gram].append(i)
    out, hits = {}, {}
    for split_name in EVAL_SPLITS:
        found = []
        for r in records:
            if splits[r["record_id"]] != split_name:
                continue
            g = _grams(_instruction(r))
            for i, _ in Counter(i for gram in g for i in index.get(gram, ())).most_common(10):
                score = len(g & train_grams[i]) / len(g | train_grams[i])
                if score >= NEAR_DUP_JACCARD:
                    found.append({"record_id": r["record_id"], "train_record_id": train[i]["record_id"],
                                  "jaccard": round(score, 2)})
                    break
        out[split_name] = {"count": len(found), "examples": found[:10]}
        hits[split_name] = len(found)
    return out, hits


def shortcuts(records: list[dict], splits: dict[str, str]) -> dict:
    """Score a planned-tool-name lookup table against the class prior, per train source.

    Args:
        records: All records.
        splits: `{record_id: split}`.

    Returns:
        `{source: {split: {"n", "tool_name_accuracy", "majority_accuracy"}}}` for validation and
        test (trajectory records have no planned action and score the prior).
    """
    tool = lambda r: (r["input"]["planned_action"] or {}).get("tool_name")
    out = {}
    for source in sorted({source_key(r) for r in records if splits[r["record_id"]] == "train"}):
        table, prior = defaultdict(Counter), Counter()
        for r in records:
            if splits[r["record_id"]] == "train" and source_key(r) == source:
                table[tool(r)][r["labels"]["decision"]] += 1
                prior[r["labels"]["decision"]] += 1
        majority = prior.most_common(1)[0][0]
        out[source] = {}
        for split_name in ("validation", "test"):
            ev = [r for r in records if splits[r["record_id"]] == split_name and source_key(r) == source]
            if not ev:
                continue
            guess = lambda r: table[tool(r)].most_common(1)[0][0] if tool(r) in table else majority
            out[source][split_name] = {
                "n": len(ev),
                "tool_name_accuracy": round(sum(guess(r) == r["labels"]["decision"] for r in ev) / len(ev), 3),
                "majority_accuracy": round(sum(majority == r["labels"]["decision"] for r in ev) / len(ev), 3)}
    return out


def markers(events_by_split: dict[str, list[dict]]) -> dict:
    """Count source-revealing strings in the Jev events.

    Args:
        events_by_split: `{split: [event, ...]}`.

    Returns:
        `{split: {marker: count}}` for config `audit.markers` (whole-word, case-insensitive).
    """
    patterns = {m: re.compile(rf"(?<![a-z0-9]){re.escape(m)}(?![a-z0-9])", re.I)
                for m in build_config()["audit"]["markers"]}
    out = {}
    for split_name, events in events_by_split.items():
        text = "\n".join(json.dumps(e, ensure_ascii=False) for e in events)
        counts = {m: len(p.findall(text)) for m, p in patterns.items()}
        out[split_name] = {m: c for m, c in counts.items() if c}
    return out


def run(records: list[dict], splits: dict[str, str], events_by_split: dict[str, list[dict]]) -> dict:
    """Run every check and collect warnings.

    Args:
        records: All records (after dedup).
        splits: `{record_id: split}`.
        events_by_split: `{split: [Jev event, ...]}`.

    Returns:
        `{"overlap", "shortcuts", "markers", "warnings": [str]}`.
    """
    ov, sc, mk = overlap(records, splits), shortcuts(records, splits), markers(events_by_split)
    warnings = []
    for feature, by_split in ov.pop("_hits").items():
        for split_name, n in by_split.items():
            if n:
                warnings.append(f"{n} {split_name} records share {feature.replace('_', ' ')} with train")
    for source, by_split in sc.items():
        for split_name, s in by_split.items():
            if s["tool_name_accuracy"] >= s["majority_accuracy"] + SHORTCUT_MARGIN:
                warnings.append(f"{source} {split_name}: tool name alone scores {s['tool_name_accuracy']} "
                                f"(class prior {s['majority_accuracy']})")
    for split_name, counts in mk.items():
        if counts:
            warnings.append(f"markers in {split_name} events: {counts}")
    return {"overlap": ov, "shortcuts": sc, "markers": mk, "warnings": warnings}
