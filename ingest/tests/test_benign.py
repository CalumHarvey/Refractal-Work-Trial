from ingest.common.validate import problems
from ingest.convert import toolace, toucan, when2call


def test_toolace_call_syntax():
    """ToolACE's `[Name(arg=...)]` turns parse into calls; prose and positional args do not.

    Raises:
        AssertionError: If a call is parsed wrongly.
    """
    calls = toolace.parse_calls('[Market Trends API(trend_type="MARKET_INDEXES", country="us"), getX(n=2)]')
    assert [c["tool_name"] for c in calls] == ["Market Trends API", "getX"]
    assert calls[0]["arguments"] == {"trend_type": "MARKET_INDEXES", "country": "us"}
    assert toolace.parse_calls("Here are the results.") is None
    assert toolace.parse_calls("[f(1, 2)]") is None


def test_toucan_steps_and_final_answer_share():
    """Calls on listed tools become steps, the system prompt is dropped, and about a fifth of runs
    contribute their final answer.

    Raises:
        AssertionError: If steps or the final-answer share are wrong.
    """
    raw = [{"role": "system", "content": "tools..."}, {"role": "user", "content": "price?"},
           {"role": "assistant", "content": "", "reasoning_content": "look it up"},
           {"role": "assistant", "content": "", "function_call": {"name": "get_price", "arguments": '{"i": "BTC"}'}},
           {"role": "function", "content": "{}", "name": "get_price"},
           {"role": "assistant", "content": "", "function_call": {"name": "ghost", "arguments": "{}"}},
           {"role": "assistant", "content": "It is 100."}]
    messages, steps = toucan.messages_and_steps(raw, {"get_price"})
    assert messages[0]["role"] == "user" and [s[1]["tool_name"] for s in steps] == ["get_price", "final_answer"]
    assert steps[0][1]["reasoning"] == "look it up"
    finals = sum(any(s[1]["tool_name"] == "final_answer" for s in toucan._choose(steps, {"get_price": "read_only"}, f"run-{i}"))
                 for i in range(2000))
    assert 0.15 < finals / 2000 < 0.25


def test_when2call_options_become_allow_and_review():
    """The correct reply is ALLOW; an unwarranted tool call where asking was right is REVIEW (hallucination).

    Raises:
        AssertionError: If a label is wrong or a record is invalid.
    """
    base = {"uuid": "u1", "question": "Book it", "source": "BFCL",
            "tools": when2call.parse_tools(['{"name": "book", "description": "Book", "parameters": {"type": "dict", "properties": {}}}'])}
    correct = dict(base, correct="request_for_info", option="request_for_info",
                   action={"tool_name": "final_answer", "arguments": {"text": "Which date?"}, "reasoning": None})
    wrong = dict(base, correct="request_for_info", option="tool_call",
                 action={"tool_name": "book", "arguments": {"date": "2024-01-01"}, "reasoning": None})
    built = [when2call.to_record(f"u1:{x['option']}", x, "rev") for x in (correct, wrong)]
    built = [rec.build(rid) for rid, rec in built]
    assert [problems(b) for b in built] == [[], []]
    assert built[0]["labels"]["decision"] == "ALLOW" and built[1]["labels"]["decision"] == "REVIEW"
    assert built[1]["labels"]["failure_modes"] == ["hallucination"]
    assert built[0]["source"]["original_label"]["toolset"] == built[1]["source"]["original_label"]["toolset"]
