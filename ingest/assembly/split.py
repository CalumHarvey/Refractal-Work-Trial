"""Group-aware split assignment.

Records are split by group, never one by one. A group is a connected component over the group_ids
axes in config `split.axes` (per source, overridable): two records that share a key on ANY of those
axes are in the same group, transitively. With axes [task, attack] this keeps a task's steps
together AND an attack's uses together, so no attacker tool or injection text seen in training
reappears in validation / test (splitting on task alone let ASB's attacker tools, whose names give
the label away, sit in both). A group shared by several sources gets one split everywhere.

Two methods (config split.method): `hash` (a group's split comes from its hash alone: stable as data
grows) and `balanced` (groups walked largest first, ties in hash order, each put into the split
furthest below its target share: accurate when a source has few, large groups). Both are deterministic; changing
`split.salt` reshuffles.
"""
import hashlib
from collections import Counter, defaultdict

from .config import build_config, source_config, source_key

SPLITS = ("train", "validation", "test", "holdout")
AXES = ("task", "trajectory", "attack", "author")


def axes_for(rec: dict) -> list[str]:
    """The group_ids axes that bind records of this record's source together.

    Args:
        rec: A record.

    Returns:
        The source's `axes` from config if set, else `split.axes`.
    """
    return source_config(source_key(rec)).get("axes") or build_config()["split"]["axes"]


def keys(rec: dict) -> list[str]:
    """The group keys a record joins its group by.

    Args:
        rec: A record.

    Returns:
        "<axis>:<value>" for each of the record's split axes that has a value (cut to its first
        n ":"-parts where the source's `coarsen` says so, e.g. AgentDojo task keys to their suite),
        plus "<source>:<field>:<value>" for each source.original_label field in the source's
        `group_by_fields` (e.g. MCPTox's server; a list value gives one key per item, e.g. TOUCAN's servers);
        if none has, the first fallback axis that does; if none, its record_id.
    """
    gids, cfg = rec["source"]["group_ids"], source_config(source_key(rec))
    coarsen = cfg.get("coarsen") or {}
    found = [f"{a}:{_truncate(gids[a], coarsen.get(a))}" for a in axes_for(rec) if gids.get(a)]
    label = rec["source"].get("original_label") or {}
    for field in cfg.get("group_by_fields", []):
        values = label.get(field)
        for value in values if isinstance(values, list) else [values]:  # a list joins on each item
            if value is not None:
                found.append(f"{source_key(rec)}:{field}:{value}")
    if found:
        return found
    for axis in build_config()["split"].get("fallback_axes", []):
        if gids.get(axis):
            return [f"{axis}:{gids[axis]}"]
    return [f"record:{rec['record_id']}"]


def _truncate(value: str, parts: int | None) -> str:
    """Cut a group key to its first `parts` ":"-separated parts.

    Args:
        value: A group_ids value, e.g. "agentdojo:banking:instr:8496775dc6e7".
        parts: How many parts to keep; None keeps the whole value.

    Returns:
        The (possibly) shortened value, e.g. "agentdojo:banking".
    """
    return value if not parts else ":".join(value.split(":")[:parts])


def groups(records: list[dict]) -> dict[str, str]:
    """Connect records that share any group key.

    Args:
        records: Records to group.

    Returns:
        `{record_id: group id}`; the group id is the smallest key in the component (stable when
        records are added that do not merge components).
    """
    parent = {}

    def find(x: str) -> str:
        """Find a key's component root, compressing the path.

        Args:
            x: A key.

        Returns:
            The root key.
        """
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for rec in records:
        ks = keys(rec)
        for k in ks[1:]:
            a, b = find(ks[0]), find(k)
            if a != b:
                parent[max(a, b)] = min(a, b)  # smallest key becomes the root
    return {rec["record_id"]: find(keys(rec)[0]) for rec in records}


def bucket(key: str) -> float:
    """Map a group key to a stable position in [0, 1).

    Args:
        key: A group key.

    Returns:
        A number derived from SHA-256 of salt + key.
    """
    salt = build_config()["split"]["salt"]
    digest = hashlib.sha256(f"{salt}|{key}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16) / 16 ** 12


def assign_all(records: list[dict]) -> dict[str, str]:
    """Assign every record to a split, keeping each group in one split across all sources.

    All records are grouped together (see `groups`). A group containing any record of a holdout
    source goes to "holdout" whole, so a train source can never share a task, run or attack with
    held-out data (its records in such a group are moved to holdout and counted by
    `forced_to_holdout`). Remaining groups are assigned source by source in config order: a group
    already assigned via an earlier source keeps its split, the rest are placed by the configured
    method using the source's ratios.

    Args:
        records: All records.

    Returns:
        `{record_id: split}`.
    """
    method = build_config()["split"].get("method", "hash")
    is_holdout = lambda r: source_config(source_key(r))["role"] == "holdout"  # noqa: E731
    group_of = groups(records)
    held = {group_of[r["record_id"]] for r in records if is_holdout(r)}
    out = {r["record_id"]: "holdout" for r in records if group_of[r["record_id"]] in held}
    by_source = defaultdict(lambda: defaultdict(list))
    for rec in records:
        if rec["record_id"] not in out:
            by_source[source_key(rec)][group_of[rec["record_id"]]].append(rec["record_id"])
    order = [s for s in build_config()["sources"] if s in by_source] + sorted(set(by_source) - set(build_config()["sources"]))
    group_split = {}
    for source in order:
        cfg, members = source_config(source), by_source[source]
        targets = {k: v for k, v in cfg["ratios"].items() if v > 0}
        total = sum(len(ids) for ids in members.values())
        counts = Counter()
        # largest groups first (ties in hash order), so a dominant group lands in train rather than
        # being placed wherever is still empty when it comes up
        for key in sorted(members, key=lambda k: (-len(members[k]), bucket(k))):
            ids = members[key]
            if key in group_split:
                chosen = group_split[key]
            elif method == "balanced":
                # the split furthest below its target share; ties go to train, validation, test order
                chosen = max(targets, key=lambda s: (targets[s] * total - counts[s]) / targets[s])
            else:
                chosen = _by_hash(key, cfg["ratios"])
            group_split[key] = chosen
            counts[chosen] += len(ids)
            out.update({rid: chosen for rid in ids})
    return out


def forced_to_holdout(records: list[dict], splits: dict[str, str]) -> dict:
    """Count train-source records placed in holdout because their group touches held-out data.

    Args:
        records: All records.
        splits: `{record_id: split}` from `assign_all`.

    Returns:
        `{source: n}` for train sources with such records (empty when none).
    """
    return dict(Counter(source_key(r) for r in records
                        if splits[r["record_id"]] == "holdout" and source_config(source_key(r))["role"] != "holdout"))


def _by_hash(key: str, ratios: dict) -> str:
    """Pick a split from a key's hash bucket alone.

    Args:
        key: A group key.
        ratios: `{split: share}` for train / validation / test.

    Returns:
        The split whose cumulative share range contains the key's bucket.
    """
    position, edge = bucket(key), 0.0
    for name in ("train", "validation", "test"):
        edge += ratios.get(name, 0.0)
        if position < edge:
            return name
    return "test"


def leakage(records: list[dict], splits: dict[str, str]) -> dict:
    """Count group_ids keys that appear in more than one split, per axis.

    A key is "enforced" when it comes from a record whose source splits on that axis (those must
    never span splits: a non-zero count is a bug) and "informational" otherwise (e.g. ATBench's
    attack key, a coarse risk category that is expected to recur). Holdout records are included:
    a key shared between holdout and another split is reported too.

    Args:
        records: All records.
        splits: `{record_id: split}`.

    Returns:
        `{"enforced_keys_in_several_splits": n, "enforced": {axis: {...}}, "informational":
        {axis: {...}}}`, each axis entry with the number of keys, how many span several splits and
        up to 10 examples.
    """
    seen = {kind: defaultdict(lambda: defaultdict(set)) for kind in ("enforced", "informational")}
    for rec in records:
        bound = set(axes_for(rec)) if source_config(source_key(rec))["role"] != "holdout" else set()
        for axis in AXES:
            key = rec["source"]["group_ids"].get(axis)
            if key and axis != "author":  # author keys are one per benchmark: always shared
                seen["enforced" if axis in bound else "informational"][axis][key].add(splits[rec["record_id"]])
    out = {}
    for kind, by_axis in seen.items():
        out[kind] = {}
        for axis, by_key in by_axis.items():
            if kind == "enforced":
                # a key is only a leak if it also appears, from any record, in another split
                by_key = {k: v | seen["informational"][axis].get(k, set()) for k, v in by_key.items()}
            multi = {k: sorted(v) for k, v in by_key.items() if len(v) > 1}
            out[kind][axis] = {"keys": len(by_key), "keys_in_several_splits": len(multi),
                               "examples": dict(list(multi.items())[:10])}
    out["enforced_keys_in_several_splits"] = sum(a["keys_in_several_splits"] for a in out["enforced"].values())
    return out


def split_counts(records: list[dict], splits: dict[str, str]) -> dict:
    """Count records per split, by source and decision.

    Args:
        records: All records.
        splits: `{record_id: split}`.

    Returns:
        `{split: {"total": n, "by_source": {...}, "by_decision": {...}}}`.
    """
    out = {}
    for name in SPLITS:
        members = [r for r in records if splits[r["record_id"]] == name]
        out[name] = {"total": len(members),
                     "by_source": dict(Counter(source_key(r) for r in members)),
                     "by_decision": dict(Counter(str(r["labels"]["decision"]) for r in members))}
    return out
