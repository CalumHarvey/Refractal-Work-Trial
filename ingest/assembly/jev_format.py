"""Records -> Jev input traces (`refractal.agent-trace.v1`) and expected findings.

A record becomes one trace. Trace and event ids are opaque (`trace-<hash of record_id>`,
`<trace_id>-e<n>`) so no dataset name reaches Jev; expected findings carry record_id for the link back. With config
`jev.tool_list_event`, a record's tool list becomes a first `context_read` event ("tools/list": names
and descriptions), labelled block when it holds a poisoned description (mode 12). Messages then become
events in order: user turns are
`llm_call` events by the user; agent tool calls are `tool_call` (or `email_send`) events carrying the
following tool output as `tool_result`; agent text is an `llm_call` by the agent; a tool output with no
call before it is a `context_read` event. The planned action is the last event, with no result yet:
it has not run. Only `input` is used, so nothing that encodes the answer reaches Jev.

Expected findings use Jev's vocabulary (`allow` / `block`); see config `jev` for how REVIEW and tool
outputs are treated. The system prompt and agent reasoning have no field in the event schema and are
left out.
"""
import hashlib
import json
from datetime import datetime, timedelta

from ..common.tools import name_tokens
from .config import build_config

SCHEMA = "refractal.agent-trace.v1"
EMAIL_WORDS = {"email", "mail", "gmail"}
DECISIONS = {"ALLOW": "allow", "BLOCK": "block"}


def _cfg() -> dict:
    """Read the `jev` section of the build config.

    Returns:
        The section as a dict.
    """
    return build_config()["jev"]


def trace_id(record_id: str) -> str:
    """Opaque, stable trace id for a record.

    Args:
        record_id: The record's id.

    Returns:
        "trace-" + the first 16 hex characters of SHA-256(record_id).
    """
    return "trace-" + hashlib.sha256(record_id.encode("utf-8")).hexdigest()[:16]


def action_type(tool_name: str, tools: list[dict]) -> str:
    """Choose the Jev action type for a tool call.

    Args:
        tool_name: The called tool.
        tools: The record's tools_available (for the tool's side_effects).

    Returns:
        "email_send" for an outward-sending email tool, otherwise "tool_call".
    """
    side = next((t.get("side_effects") for t in tools if t["name"] == tool_name), None)
    if side == "external_send" and set(name_tokens(tool_name)) & EMAIL_WORDS:
        return "email_send"
    return "tool_call"


def expected_decision(decision: str | None) -> str | None:
    """Map a record decision to Jev's vocabulary.

    Args:
        decision: "ALLOW", "BLOCK", "REVIEW" or None.

    Returns:
        "allow" / "block"; REVIEW per config `jev.review_as` ("block", "allow", or None for
        "exclude"); None when there is no decision.
    """
    if decision == "REVIEW":
        return None if _cfg()["review_as"] == "exclude" else _cfg()["review_as"]
    return DECISIONS.get(decision)


def to_trace(rec: dict) -> dict:
    """Convert one record into Jev input events and expected findings.

    Args:
        rec: A record (after backfill).

    Returns:
        `{"trace_id", "events": [...], "target_event_id": str | None, "expected": [...]}`. Each expected item is
        `{"event_id" or "trace_id", "decision", "source"}`, where source is "decision" (the planned
        action, or the whole trace for trajectory records) or "adversarial_location" (a tool output
        holding an injection).
    """
    inp, rid = rec["input"], trace_id(rec["record_id"])
    tools = inp.get("tools_available") or []
    base = datetime.fromisoformat(_cfg()["timestamp_base"].replace("Z", "+00:00"))
    events, located = [], {}  # message index -> (event_id, "tool_result" | "event")

    def add(actor_kind: str, action: str, **fields) -> str:
        """Append one event.

        Args:
            actor_kind: "user" or "agent".
            action: The Jev action type.
            **fields: Optional event fields (tool_name, tool_args, tool_result, payload).

        Returns:
            The new event's id.
        """
        event_id = f"{rid}-e{len(events)}"
        ts = (base + timedelta(seconds=len(events))).isoformat().replace("+00:00", "Z")
        event = {"schema": SCHEMA, "event_id": event_id, "trace_id": rid, "timestamp": ts,
                 "actor": {"kind": actor_kind, "id": actor_kind}, "action_type": action}
        event.update({k: v for k, v in fields.items() if v is not None})
        event["metadata"] = {"provenance": "human" if actor_kind == "user" else "ai"}
        events.append(event)
        return event_id

    tool_list = None
    if _cfg().get("tool_list_event") and tools:
        # What an MCP client reads from `tools/list` before the conversation: names and descriptions,
        # where a poisoned description (MCPTox, ATBench tool-description injection) lives.
        tool_list = add("agent", "context_read", tool_name="tools/list",
                        payload=json.dumps([{"name": t["name"], "description": t.get("description")} for t in tools],
                                           ensure_ascii=False))

    messages, i = inp["messages"], 0
    while i < len(messages):
        m = messages[i]
        if m["role"] == "user":
            add("user", "llm_call", payload=m["content"])
        elif m["role"] in ("assistant", "agent") and m.get("tool_call"):
            call = m["tool_call"]
            result = messages[i + 1] if i + 1 < len(messages) and messages[i + 1]["role"] == "tool" else None
            eid = add("agent", action_type(call["tool_name"], tools), tool_name=call["tool_name"],
                      tool_args=call["arguments"], tool_result=result["content"] if result else None)
            if result:
                located[i + 1] = (eid, "tool_result")
                i += 1
        elif m["role"] in ("assistant", "agent"):
            if m.get("content"):
                add("agent", "llm_call", payload=m["content"])
        elif m["role"] == "tool":
            located[i] = (add("agent", "context_read", tool_name=m.get("tool_name"), payload=m["content"]), "event")
        i += 1

    target = None
    action = inp.get("planned_action")
    if action and action["tool_name"] == "final_answer":
        target = add("agent", "llm_call", payload=str(action["arguments"].get("text", "")))
    elif action:
        target = add("agent", action_type(action["tool_name"], tools), tool_name=action["tool_name"],
                     tool_args=action["arguments"])

    expected = []
    decision = expected_decision(rec["labels"]["decision"])
    if decision and target:
        expected.append({"event_id": target, "decision": decision, "source": "decision"})
    elif decision and rec["granularity"] == "trajectory":
        expected.append({"trace_id": rid, "decision": decision, "source": "decision"})
    locations = rec["labels"]["adversarial_locations"] or []
    if tool_list and 12 in (rec["labels"]["failure_modes"] or []) and any(loc["kind"] == "tool" for loc in locations):
        expected.append({"event_id": tool_list, "decision": "block", "source": "adversarial_location"})
    if _cfg()["label_tool_results"]:
        for loc in locations:
            hit = located.get(loc.get("message_index")) if loc["kind"] == "message" else None
            if hit:
                eid, where = hit
                expected.append({"event_id": f"{eid}:tool_result" if where == "tool_result" else eid,
                                 "decision": "block", "source": "adversarial_location"})
    return {"trace_id": rid, "events": events, "target_event_id": target, "expected": expected}
