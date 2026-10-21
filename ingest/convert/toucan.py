"""TOUCAN -> AgentDecisionRecords (benign step records from real MCP-server agent runs).

Spec: `datasets.toucan` in label-schema/dataset_mappings.yaml. TOUCAN runs are ordinary user
tasks on real MCP servers with real tool execution; no attacker is involved, so every kept step is
ALLOW by construction. Only well-rated runs are used, a few steps per run (calls with side effects
first: the hard benign cases), and a capped number of runs per MCP server.
"""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

from ..common.paths import mappings
from ..common.react import parse_arguments
from ..common.record import Record
from ..common.rules import RuleSet
from ..common.text import normalise, sha1_12
from ..common.tools import side_effects

DATASET = "toucan"
RULES = RuleSet(DATASET)
STATS: Counter = Counter()  # filled by iter_source, reported by report_extras


def _cfg() -> dict:
    """Read the dataset's selection settings from the mappings.

    Returns:
        `datasets.toucan.selection`.
    """
    return mappings()["datasets"][DATASET]["selection"]


def _order(key: str) -> str:
    """Stable pseudo-random order for sampling.

    Args:
        key: Any identifier.

    Returns:
        A hex digest to sort by.
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def tools_from(available: str) -> list[dict]:
    """Turn TOUCAN's OpenAI-style tool list into schema tools.

    Args:
        available: The `available_tools` JSON string.

    Returns:
        Schema tools (name, description, parameters, origin "mcp", side effects from the name).
    """
    out = []
    for t in json.loads(available or "[]"):
        fn = t.get("function", t)
        out.append({"name": fn["name"], "description": fn.get("description"),
                    "parameters_schema": fn.get("parameters") if isinstance(fn.get("parameters"), dict) else None,
                    "origin": "mcp", "side_effects": side_effects(fn["name"])})
    return out


def messages_and_steps(raw: list[dict], tool_names: set[str]) -> tuple[list[dict], list[tuple[int, dict]]]:
    """Convert a TOUCAN message list into schema messages and the decision points in it.

    Args:
        raw: The run's messages (system, user, assistant with `reasoning_content` or
            `function_call`, function outputs).
        tool_names: Names in the run's tool list.

    Returns:
        `(messages, steps)`: schema messages (the system prompt is dropped: it only repeats the
        tool list), and `(message_index, planned_action)` for each assistant tool call on a listed
        tool, plus the final answer as a `final_answer` pseudo-call.
    """
    messages, steps, reasoning = [], [], None
    for m in raw:
        role = m.get("role")
        if role == "system":
            continue
        if role == "user":
            messages.append({"role": "user", "content": m.get("content") or "", "trust": "principal"})
        elif role == "assistant" and m.get("function_call"):
            fc = m["function_call"]
            call = {"tool_name": fc["name"], "arguments": parse_arguments(fc.get("arguments") or ""), "reasoning": reasoning}
            if fc["name"] in tool_names:
                steps.append((len(messages), call))
            else:
                STATS["calls_to_unlisted_tool_skipped"] += 1
            messages.append({"role": "assistant", "content": "", "trust": "agent_generated", "tool_call": call})
            reasoning = None
        elif role == "assistant" and m.get("reasoning_content") and not m.get("content"):
            reasoning = m["reasoning_content"]
        elif role == "assistant":
            messages.append({"role": "assistant", "content": m.get("content") or "", "trust": "agent_generated"})
            reasoning = None
        elif role in ("function", "tool"):
            messages.append({"role": "tool", "content": m.get("content") or "", "trust": "tool_output", "tool_name": m.get("name")})
    last = messages[-1] if messages else None
    if last and last["role"] == "assistant" and not last.get("tool_call") and last["content"].strip():
        steps.append((len(messages) - 1, {"tool_name": "final_answer", "arguments": {"text": last["content"]}, "reasoning": None}))
    return messages, steps


def _choose(steps: list[tuple[int, dict]], tools: dict[str, str], uuid: str) -> list[tuple[int, dict]]:
    """Pick the steps to keep from one run.

    Args:
        steps: Decision points from `messages_and_steps`.
        tools: `{tool name: side effects}`.
        uuid: The run id (for a stable choice).

    Returns:
        Up to `max_steps_per_run` steps: tool calls with side effects first, then read-only calls,
        in a stable order; the final answer only for runs selected by `final_answer_share`.
    """
    cfg = _cfg()
    calls = [s for s in steps if s[1]["tool_name"] != "final_answer"]
    calls.sort(key=lambda s: (tools.get(s[1]["tool_name"]) in ("read_only", "unknown"), _order(f"{uuid}:{s[0]}")))
    chosen = calls[:cfg["max_steps_per_run"]]
    final = [s for s in steps if s[1]["tool_name"] == "final_answer"]
    # salted: runs are picked per server by their unsalted hash, which would bias this choice
    if final and int(_order(f"final:{uuid}")[:4], 16) / 0xFFFF < cfg["final_answer_share"]:
        chosen = chosen[:cfg["max_steps_per_run"] - 1] + final
    return sorted(chosen, key=lambda s: s[0])


def _sensitive(r: dict) -> bool:
    """Check whether a run calls a tool with side effects (write, send, delete, pay, execute).

    Args:
        r: A raw run.

    Returns:
        True if any function_call names a listed tool whose side effects are not read-only/unknown.
    """
    effects = {t["name"]: t["side_effects"] for t in tools_from(r["available_tools"])}
    return any(effects.get((m.get("function_call") or {}).get("name")) not in (None, "read_only", "unknown")
               for m in json.loads(r["messages"]))


def iter_source(snapshot: Path):
    """Select benign decision points from the downloaded shards.

    Runs are kept if their response quality score is at least `min_response_score`. Per primary MCP
    server, at most `max_sensitive_runs_per_server` runs that call a tool with side effects (the hard
    benign cases) and `max_runs_per_server` other runs are kept, in a stable pseudo-random order.

    Args:
        snapshot: The TOUCAN snapshot folder (parquet shards per teacher model).

    Yields:
        `(original_id, item)` pairs; original_id is "<teacher>:<uuid>:<message index>".
    """
    STATS.clear()
    cfg = _cfg()
    by_server = defaultdict(list)
    for shard in sorted(snapshot.glob("*/*.parquet")):
        teacher = shard.parent.name
        for r in pq.read_table(shard).to_pylist():
            STATS["runs"] += 1
            try:
                score = json.loads(r["response_quality_assessment"])["overall_score"]
            except (TypeError, ValueError, KeyError):
                score = None
            if score is None or score < cfg["min_response_score"]:
                STATS["runs_below_quality"] += 1
                continue
            servers = sorted({s["server_name"] for s in json.loads(r["metadata"])["mcp_servers"]})
            by_server[servers[0] if servers else "?"].append((teacher, r, servers))
    for server in sorted(by_server):
        runs = sorted(by_server[server], key=lambda x: _order(x[1]["uuid"]))
        sensitive = [x for x in runs if _sensitive(x[1])]
        other = [x for x in runs if not _sensitive(x[1])]
        keep = sensitive[:cfg["max_sensitive_runs_per_server"]] + other[:cfg["max_runs_per_server"]]
        STATS["runs_over_server_cap"] += len(runs) - len(keep)
        for teacher, r, servers in keep:
            tools = tools_from(r["available_tools"])
            messages, steps = messages_and_steps(json.loads(r["messages"]), {t["name"] for t in tools})
            effects = {t["name"]: t["side_effects"] for t in tools}
            STATS["runs_used"] += 1
            STATS["sensitive_runs_used"] += _sensitive(r)
            for index, action in _choose(steps, effects, r["uuid"]):
                yield f"{teacher}:{r['uuid']}:{index}", {
                    "teacher": teacher, "uuid": r["uuid"], "servers": servers, "subset": r["subset_name"],
                    "question": r["question"], "messages": messages[:index], "action": action, "tools": tools}


# ---- rules (registration order = application order) ---------------------------------------
@RULES.rule("tc.benign")
def benign(item, rec: Record) -> bool:
    """tc.benign: an ordinary user task on real MCP servers with no attacker -> ALLOW.

    Args:
        item: The source item.
        rec: The Record being built.

    Returns:
        True for every record.
    """
    rec.set("decision", "ALLOW", "by_construction", "tc.benign")
    rec.set("attack_vector", "none", "by_construction", "tc.benign")
    rec.set_no_modes("by_construction", "tc.benign")
    rec.set("action_relation", "user_task", "by_construction", "tc.benign")
    rec.set("adversarial_locations", [], "by_construction", "tc.benign")
    rec.set("hard_negative", False, "by_construction", "tc.benign")
    return True


# ---- record --------------------------------------------------------------------------------
def to_record(original_id: str, item: dict, revision: str) -> tuple[str, Record]:
    """Convert one selected step into a Record.

    Args:
        original_id: From `iter_source`.
        item: The source item.
        revision: The snapshot revision, written to `source.dataset_version`.

    Returns:
        `(record_id, record)`: "toucan:" + original_id and the Record.
    """
    rec = Record(DATASET, original_id, "step")
    rec.input = {"system_prompt": None, "user_prompt": item["question"], "messages": item["messages"],
                 "tools_available": item["tools"], "planned_action": item["action"], "principal": None, "modality": "text"}
    planned = item["action"]["tool_name"]
    rec.source.update({
        "dataset_version": revision, "original_split": None, "step_index": len(item["messages"]),
        "generator_model": item["teacher"], "license": "Apache-2.0",
        "original_label": {"subset": item["subset"], "teacher": item["teacher"], "servers": item["servers"],
                           "planned_side_effects": next((t["side_effects"] for t in item["tools"] if t["name"] == planned),
                                                        "none" if planned == "final_answer" else "unknown")},
    })
    rec.source["group_ids"] = {"task": f"toucan:question:{sha1_12(normalise(item['question'] or ''))}",
                               "attack": None, "trajectory": f"toucan:{item['uuid']}", "author": "toucan:benchmark_authors"}
    RULES.apply(item, rec)
    return f"toucan:{original_id}", rec


# ---- dataset-specific report section ---------------------------------------------------------
EXPECTED = {"runs": 35227}


def report_extras(records: list[dict]) -> dict:
    """Build the TOUCAN section of report.json.

    Args:
        records: The valid converted records.

    Returns:
        Reconciliation of the run count, the selection funnel, and records by planned side effect,
        teacher model and number of servers.
    """
    ol = lambda r: r["source"]["original_label"]  # noqa: E731
    return {
        "reconciliation": {k: {"expected": v, "measured": STATS[k], "ok": STATS[k] == v} for k, v in EXPECTED.items()},
        "funnel": dict(sorted(STATS.items())),
        "by_planned_side_effects": dict(Counter(ol(r)["planned_side_effects"] for r in records)),
        "by_teacher": dict(Counter(ol(r)["teacher"] for r in records)),
        "servers": len({s for r in records for s in ol(r)["servers"]}),
        "runs": len({r["source"]["group_ids"]["trajectory"] for r in records}),
    }
