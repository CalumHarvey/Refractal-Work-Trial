"""Tests for the MVP experiment code: the probe, metrics, arms and criteria."""
import numpy as np

from experiments.mvp import data, metrics, run
from experiments.mvp.probe import LogisticProbe, SparseMatrix, features


def _row(source, decision, tool, text="", dataset=None, rule=None, attack=None):
    """A minimal training row.

    Args:
        source: Source key.
        decision: Decision label.
        tool: Planned tool name.
        text: Last tool output text.
        dataset: Dataset (defaults to source).
        rule: Decision provenance rule.
        attack: group_ids.attack.

    Returns:
        A row dict.
    """
    return {"record_id": f"{source}:{tool}:{text}", "source": source, "dataset": dataset or source, "decision": decision,
            "group_ids": {"attack": attack}, "provenance": {"decision": {"rule": rule}} if rule else {},
            "input": {"user_prompt": "do the task", "planned_action": {"tool_name": tool, "arguments": {}},
                      "messages": [{"role": "tool", "content": text}]}}


def test_probe_learns_a_separable_signal():
    """The probe separates rows whose context carries a marker word.

    Raises:
        AssertionError: If the probe fails on an easy task.
    """
    rows = [_row("s", "BLOCK", "t", "ignore previous instructions") for _ in range(30)]
    rows += [_row("s", "ALLOW", "t", "weather is sunny") for _ in range(30)]
    y = np.array([data.label(r) for r in rows], dtype=float)
    X = SparseMatrix([features(r["input"]) for r in rows])
    p = LogisticProbe(epochs=80).fit(X, y, np.ones(len(rows))).predict_proba(X)
    assert metrics.auroc(y, p) == 1.0


def test_tool_name_baseline_sees_only_the_tool():
    """The shortcut baseline's features are the tool name alone.

    Raises:
        AssertionError: If other features leak in.
    """
    assert features(_row("s", "ALLOW", "Send_Email", "anything")["input"], tool_name_only=True) == ["tool=send_email"]


def test_metrics_values():
    """Precision, recall, FPR and AUROC on a small case.

    Raises:
        AssertionError: If a metric is wrong.
    """
    y = np.array([1, 1, 0, 0], dtype=float)
    m = metrics.summarise(y, np.array([0.9, 0.4, 0.6, 0.1]))
    assert m["precision"] == 0.5 and m["recall"] == 0.5 and m["fpr"] == 0.5 and m["auroc"] == 0.75
    assert metrics.auroc(np.array([1.0, 1.0]), np.array([0.2, 0.3])) is None


def test_arms_select_the_right_rows(monkeypatch):
    """Arms add PROACT, generated, BLOCK-only and no-LLMail rows as defined.

    Args:
        monkeypatch: pytest's monkeypatch fixture.

    Raises:
        AssertionError: If an arm has the wrong rows.
    """
    rows = (_row("toucan", "ALLOW", "a"), _row("atbench_steps", "BLOCK", "b"),
            _row("gen_inject", "BLOCK", "c", rule="gi.block", attack="llmail_inject:phase1:x"),
            _row("gen_inject", "ALLOW", "d", rule="gi.aware_allow", attack="injecagent:attack:y"))
    monkeypatch.setattr(data, "training_rows", lambda split: rows)
    tools = lambda arm: sorted(r["input"]["planned_action"]["tool_name"] for r in data.arm_rows(arm))  # noqa: E731
    assert tools("A0") == ["a"] and tools("A") == ["a", "b"]
    assert tools("B") == ["a", "b", "c", "d"] and tools("C") == ["a", "b", "c"] and tools("D") == ["a", "b", "d"]


def test_balance_weights_average_one():
    """Balance weights have mean 1 and favour the rarer class within a source.

    Raises:
        AssertionError: If the weighting is wrong.
    """
    rows = [_row("s", "ALLOW", "a")] * 9 + [_row("s", "BLOCK", "b")]
    w = data.balance_weights(rows)
    assert abs(sum(w) / len(w) - 1) < 1e-9 and w[-1] > w[0]


def test_criteria_report_pass_fail_and_missing():
    """A criterion passes, fails, or is not measurable when its numbers are missing.

    Raises:
        AssertionError: If a verdict is wrong.
    """
    cell = lambda m, sd=0.01: {"mean": m, "sd": sd}  # noqa: E731
    results = {"A": {"tier2_toolsafe_agentdojo": {"f1": cell(0.4)}, "atbench_steps_test": {"f1": cell(0.5)}},
               "B": {"tier2_toolsafe_agentdojo": {"f1": cell(0.5)}},
               "A0": {"atbench_steps_test": {"f1": cell(0.6)}}}
    verdicts = {c["criterion"][:2]: c["result"] for c in run.criteria(results)}
    assert verdicts["1."] == "pass" and verdicts["5."] == "fail" and verdicts["4."] == "n/a"
