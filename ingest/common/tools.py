"""Tool parsing helpers: `side_effects` from a keyword table over the tool name.

Production gets side_effects from a tool registry; for benchmark tools we approximate it from the
name's words. The first matching class wins, in the order below (most dangerous first). The report
shows the resulting distribution so the table can be tuned.
"""
import ast
import re

SIDE_EFFECT_KEYWORDS: list[tuple[str, set[str]]] = [
    ("code_exec", {"execute", "exec", "run", "shell", "terminal", "command", "cmd", "script", "eval",
                   "python", "bash", "sql", "compile", "deploy"}),
    ("financial", {"pay", "payment", "transfer", "purchase", "buy", "refund", "wire", "withdraw",
                   "deposit", "trade", "invoice", "charge", "money", "fund", "funds", "transaction", "order"}),
    ("destructive", {"delete", "remove", "drop", "destroy", "wipe", "erase", "purge", "terminate",
                     "kill", "revoke", "cancel", "reset", "shutdown", "disable", "uninstall", "ban"}),
    ("external_send", {"send", "email", "mail", "post", "tweet", "message", "sms", "share", "upload",
                       "publish", "webhook", "notify", "notification", "call", "reply", "forward",
                       "broadcast", "invite", "dm"}),
    ("write", {"create", "update", "add", "set", "write", "edit", "modify", "insert", "save", "schedule",
               "book", "register", "enable", "install", "change", "assign", "move", "rename", "submit",
               "approve", "grant", "log", "record", "store", "put", "patch", "upsert", "apply", "mark"}),
    ("read_only", {"get", "list", "search", "read", "fetch", "find", "query", "retrieve", "check", "view",
                   "lookup", "extract", "show", "describe", "count", "lookup", "browse", "scan", "analyze",
                   "analyse", "summarize", "summarise", "calculate", "compute", "convert", "translate",
                   "validate", "verify", "monitor", "track", "detect", "download", "load", "inspect"}),
]

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def name_tokens(name: str) -> list[str]:
    """Split a tool name into lowercase words.

    camelCase, snake_case, kebab-case and other punctuation all split.

    Args:
        name: Tool name, e.g. "sendEmail_v2".

    Returns:
        Lowercase words, e.g. ["send", "email", "v2"].
    """
    spaced = _CAMEL.sub(" ", name)
    return [t for t in re.split(r"[^a-zA-Z0-9]+", spaced.lower()) if t]


_TOOL_HEADER = re.compile(r"^([A-Za-z_][A-Za-z0-9_.\-]*):\s?(.*)$")
_PARAM_LINE = re.compile(r"^\s+([A-Za-z_][A-Za-z0-9_]*):\s*(\{.*\})\s*$")


def parse_tool_text(text: str) -> list[dict]:
    """Parse tool descriptions written as text blocks.

    Format (ToolSafe's `env_info`): blocks separated by blank lines; the first line is
    "name: description", optionally followed by "  parameters:" and one
    "    param: {python-literal schema}" line per parameter.

    Args:
        text: The tool description text.

    Returns:
        `{"name", "description", "parameters_schema"}` per tool, in order. parameters_schema is a
        JSON-Schema-style object (`{"type": "object", "properties": {...}}`) or None when no
        parameters are listed; a parameter line that cannot be parsed is kept as {"raw": line}.
    """
    tools = []
    for block in re.split(r"\n\s*\n", (text or "").strip()):
        lines = block.split("\n")
        head = _TOOL_HEADER.match(lines[0].strip())
        if not head:
            if tools:  # a description that ran over a blank line
                tools[-1]["description"] = (tools[-1]["description"] or "") + "\n\n" + block.strip()
            continue
        description, properties = [head.group(2)], {}
        in_params = False
        for line in lines[1:]:
            if line.strip() == "parameters:":
                in_params = True
                continue
            param = _PARAM_LINE.match(line) if in_params else None
            if param:
                try:
                    properties[param.group(1)] = ast.literal_eval(param.group(2))
                except (ValueError, SyntaxError):
                    properties[param.group(1)] = {"raw": param.group(2)}
            elif not in_params:
                description.append(line.strip())
        tools.append({"name": head.group(1), "description": "\n".join(d for d in description if d).strip() or None,
                      "parameters_schema": {"type": "object", "properties": properties} if properties else None})
    return tools


def side_effects(name: str) -> str:
    """Classify a tool by its likely side effects from the words in its name.

    The first SIDE_EFFECT_KEYWORDS class (most dangerous first) sharing a word with the name wins.

    Args:
        name: Tool name.

    Returns:
        "code_exec", "financial", "destructive", "external_send", "write", "read_only" or
        "unknown".
    """
    tokens = set(name_tokens(name))
    for effect, words in SIDE_EFFECT_KEYWORDS:
        if tokens & words:
            return effect
    return "unknown"
