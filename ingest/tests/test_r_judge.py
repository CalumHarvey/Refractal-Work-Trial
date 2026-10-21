import json

import pytest

from ingest.common.paths import raw_snapshot
from ingest.common.validate import problems
from ingest.convert import r_judge


def test_rule_ids_match_mappings():
    """Every YAML rule id is implemented, and every implemented id is in the YAML.

    Raises:
        AssertionError: If the code and the mappings YAML disagree.
    """
    assert r_judge.RULES.missing_from_code() == []
    assert r_judge.RULES.missing_from_yaml() == []


@pytest.mark.parametrize("action, tool, args", [
    ("GmailReadEmail{'email_id': 'email001'}", "GmailReadEmail", {"email_id": "email001"}),
    ('SendMessage: {"user": "Alice"}', "SendMessage", {"user": "Alice"}),
    ('AugustSmartLockGrantGuestAccess\nAction Input: {"guest_ids": ["g1"], "permanent": true}',
     "AugustSmartLockGrantGuestAccess", {"guest_ids": ["g1"], "permanent": True}),
])
def test_tool_call_forms(action, tool, args):
    """Each tool-call form in the data parses to the right tool name and arguments.

    Args:
        action: A raw agent action.
        tool: The expected tool name.
        args: The expected arguments.

    Raises:
        AssertionError: If the action is not parsed as that call.
    """
    call, text = r_judge.parse_action(action)
    assert call == {"tool_name": tool, "arguments": args} and text == ""


@pytest.mark.parametrize("text, expected", [
    ('{"body": "Hello,\nBye"}', {"body": "Hello,\nBye"}),
    ("{'content': \"Dear John,\nThanks\"}", {"content": "Dear John,\nThanks"}),
    ('{"amount": 10000/2800.45}', {"raw": '{"amount": 10000/2800.45}'}),
])
def test_parse_args_line_breaks_and_fallback(text, expected):
    """Raw line breaks inside strings still parse; arithmetic falls back to raw text.

    Args:
        text: Raw argument text.
        expected: The expected parsed arguments.

    Raises:
        AssertionError: If the result differs.
    """
    assert r_judge.parse_args(text) == expected


@pytest.mark.parametrize("action, text", [
    ("Final Answer: I have done it.", "I have done it."),
    ("Woman: I love you.", "Woman: I love you."),
    (None, ""),
])
def test_text_actions_are_not_tool_calls(action, text):
    """Final answers and plain replies (even "Name: text") are message text, not tool calls.

    Args:
        action: A raw agent action.
        text: The expected message text.

    Raises:
        AssertionError: If the action is parsed as a tool call or the text is wrong.
    """
    assert r_judge.parse_action(action) == (None, text)


@pytest.fixture(scope="module")
def converted():
    """Fixture: every run, converted.

    Returns:
        `(raw_run, built_record)` pairs.
    """
    out = []
    for oid, run in r_judge.iter_source(raw_snapshot("r_judge")):
        rid, rec = r_judge.to_record(oid, run, "test")
        out.append((run, rec.build(rid)))
    return out


def test_records_are_valid(converted):
    """Converted records pass the schema and the extra invariants.

    Args:
        converted: The fixture's `(raw_run, built_record)` pairs.

    Raises:
        AssertionError: If any record has a problem.
    """
    for _, rec in converted:
        assert problems(rec) == [], rec["record_id"]


def test_judging_prompt_and_labels_stay_out_of_input(converted):
    """The `goal` judging prompt and the risk description never reach input, and there is no tool list.

    Args:
        converted: The fixture's `(raw_run, built_record)` pairs.

    Raises:
        AssertionError: If any of them appears in a record's input.
    """
    for run, rec in converted:
        text = json.dumps(rec["input"])
        assert run["goal"] not in text
        assert not run.get("risk_description") or run["risk_description"] not in text
        assert "tools_available" not in rec["input"]
