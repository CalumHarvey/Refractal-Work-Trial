"""Parser for ReAct-style agent text: "(1) Thought: ... (2) Action: ... (3) Action Input: ... Observation: ...".

Used by ToolSafe, whose histories and actions are stored as this text rather than as messages.
Step numbers are not trusted (some steps use "(3) Action" / "(4) Action Input"); only the labels are.
"""
import ast
import json
import re

_STEP_START = re.compile(r"\(1\)\s*Thought:")
_ACTION = re.compile(r"\(\d+\)\s*Action:\s*([^\n]*)")
_ACTION_INPUT = re.compile(r"\(\d+\)\s*Action Input:\s*")
_OBSERVATION = re.compile(r"\n?Observation:\s*")
_FINAL = re.compile(r"Final Answer:\s*")
_TOOL_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")
_LEADING_NAME = re.compile(r"^([A-Za-z_][A-Za-z0-9_.\-]*)")
# "Action: None" (905 history steps and 343 actions in ToolSafe) means the agent called no tool.
_NO_TOOL = {"none", "null", "n/a", "na", "nothing", "no_action", "final"}


def _is_tool_name(name: str) -> bool:
    """Check whether an Action value names a tool.

    Args:
        name: The text after "Action:", stripped of spaces and backticks.

    Returns:
        True for an identifier that is not a "no tool" word such as "None".
    """
    return bool(_TOOL_NAME.match(name)) and name.lower() not in _NO_TOOL


_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```\s*$")


def _leading_json(text: str):
    """Decode the first JSON object or array in `text`, ignoring anything after it.

    Args:
        text: Text that contains a JSON value, possibly followed by commentary.

    Returns:
        The decoded value.

    Raises:
        ValueError: If no JSON object or array can be decoded.
    """
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if start < 0:
        raise ValueError("no JSON value")
    return json.JSONDecoder(strict=False).raw_decode(text[start:])[0]


def parse_arguments(text: str) -> dict:
    """Parse an Action Input as JSON or a Python literal.

    Tolerates Markdown code fences and commentary after the value.

    Args:
        text: The argument text after "Action Input:".

    Returns:
        The arguments as a dict. A non-dict value is wrapped as {"value": ...}; empty text gives
        {}; text that cannot be parsed is kept as {"raw": text}.
    """
    text = text.strip()
    if not text:
        return {}
    unfenced = _FENCE.sub("", text).strip()
    parsers = (json.loads, lambda s: json.loads(s, strict=False), ast.literal_eval, _leading_json)
    for candidate in (text, unfenced):
        for parse in parsers:
            try:
                value = parse(candidate)
                return value if isinstance(value, dict) else {"value": value}
            except (ValueError, SyntaxError):
                continue
    return {"raw": text}


def parse_step(text: str) -> dict:
    """Parse one step: its thought, an optional tool call, an optional final answer and observation.

    Args:
        text: One step's text, starting at "(1) Thought:".

    Returns:
        `{"thought", "tool_call", "final_answer", "observation"}`. tool_call is
        `{"tool_name", "arguments"}` or None; the others are strings or None. A step whose
        "Action:" is not a tool name (e.g. a sentence) gets no tool_call.
    """
    body = _STEP_START.sub("", text, count=1)
    obs = _OBSERVATION.search(body)
    observation = body[obs.end():].strip() if obs else None
    if obs:
        body = body[:obs.start()]
    # The last "Action:" naming a real tool is the call; earlier ones can be sentences.
    actions = [a for a in _ACTION.finditer(body) if _is_tool_name(a.group(1).strip().strip("`"))]
    action = actions[-1] if actions else None
    action_name = action.group(1).strip().strip("`") if action else None
    if action is None:
        # Malformed name followed by an Action Input ("update_file (I'm aware...)", "SimulatedPh phishing"):
        # keep the leading identifier - it is what the agent tried to call.
        for a in reversed(list(_ACTION.finditer(body))):
            lead = _LEADING_NAME.match(a.group(1).strip().strip("`"))
            if lead and _is_tool_name(lead.group(1)) and _ACTION_INPUT.search(body[a.end():]):
                action, action_name = a, lead.group(1)
                break
    first_action = _ACTION.search(body)
    final = _FINAL.search(body)
    cut = [m.start() for m in (first_action, final) if m]
    thought = body[:min(cut) if cut else len(body)].strip() or None

    tool_call = None
    if action:
        rest = body[action.end():]
        inp = _ACTION_INPUT.search(rest)
        args_text = rest[inp.end():] if inp else ""
        fin = _FINAL.search(args_text)
        if fin:
            args_text = args_text[:fin.start()]
        tool_call = {"tool_name": action_name, "arguments": parse_arguments(args_text)}
    final_answer = body[final.end():].strip() if final and not tool_call else None
    if not tool_call and final_answer is None:
        # "(2) Action: Final Answer" followed by the answer (or an Action Input holding it).
        named = [a for a in _ACTION.finditer(body) if a.group(1).strip().lower().rstrip(":") == "final answer"]
        if named:
            rest = body[named[-1].end():]
            inp = _ACTION_INPUT.search(rest)
            final_answer = (rest[inp.end():] if inp else rest).strip()
    return {"thought": thought, "tool_call": tool_call, "final_answer": final_answer, "observation": observation}


def parse_history(text: str) -> list[dict]:
    """Split a ReAct history into steps and parse each one.

    Args:
        text: The full history text (may be empty).

    Returns:
        Parsed steps in order (see `parse_step`); an empty list for an empty history. Text before
        the first "(1) Thought:" (e.g. a history that starts with "Observation: ...") becomes a
        leading step with only that observation or text.
    """
    text = text or ""
    starts = [m.start() for m in _STEP_START.finditer(text)]
    bounds = starts + [len(text)]
    steps = [parse_step(text[a:b]) for a, b in zip(bounds, bounds[1:])]
    prefix = text[:starts[0]] if starts else text
    if prefix.strip():
        steps.insert(0, parse_step(prefix))
    return steps
