"""Tests for the single pipeline command: stage choice, settings, and quota / failure handling."""
import pytest

import pipeline.__main__ as cli
from pipeline import stages


def test_stage_choice_keeps_pipeline_order():
    """--stages, --from, --skip, --offline and --experiment combine, always in pipeline order.

    Raises:
        AssertionError: If the wrong stages are chosen.
    """
    pick = lambda *argv: cli.stages_to_run(cli.parse(list(argv)))  # noqa: E731
    assert pick("--stages", "deliver", "build") == ["build", "deliver"]
    assert pick("--offline") == [s for s in cli.pipeline_config()["stages"] if s not in stages.MODEL_STAGES]
    assert pick("--from", "build") == ["build", "deliver"]
    assert pick("--from", "build", "--experiment") == ["build", "deliver", "experiment"]
    assert "libraries" not in pick("--skip", "libraries")


def test_settings_overrides():
    """Command-line values override config/pipeline.yaml; selection flags reach delivery.

    Raises:
        AssertionError: If an override is lost.
    """
    s = cli.settings_from(cli.parse(["--groups", "7", "--diagnostic-groups", "2", "--send", "--kinds", "real"]))
    assert s.groups == {"train": 7, "diagnostic": 2} and s.dry_run is False
    assert s.selection.kinds == ("real",)
    assert cli.settings_from(cli.parse(["--dry-run"])).dry_run is True


@pytest.fixture
def fake_runners(monkeypatch):
    """Replace every stage with a recorder; tests choose which one stops or fails.

    Args:
        monkeypatch: pytest's monkeypatch fixture.

    Returns:
        `{"ran": [...], "behaviour": {stage: exception}}`.
    """
    state = {"ran": [], "behaviour": {}}

    def make(name):
        """Build a fake stage.

        Args:
            name: Stage name.

        Returns:
            A function that records the call and raises the configured exception, if any.
        """
        def run(settings):
            """Record the call.

            Args:
                settings: Ignored.

            Returns:
                An empty status.
            """
            state["ran"].append(name)
            if name in state["behaviour"]:
                raise state["behaviour"][name]
            return {}
        return run
    monkeypatch.setattr(cli, "RUNNERS", {name: make(name) for name in stages.STAGES})
    return state


def test_quota_skips_model_stages_but_still_builds(fake_runners, monkeypatch):
    """A quota stop in PROACT skips generation, still builds and delivers, and exits 3.

    Args:
        fake_runners: The recorder fixture.
        monkeypatch: pytest's monkeypatch fixture.

    Raises:
        AssertionError: If the wrong stages run or the exit code is wrong.
    """
    config = {**cli.pipeline_config(), "on_quota": "continue"}
    monkeypatch.setattr(cli, "pipeline_config", lambda: config)
    fake_runners["behaviour"]["proact"] = stages.QuotaStop("daily quota")
    assert cli.main([]) == 3
    assert "generate" not in fake_runners["ran"] and fake_runners["ran"][-2:] == ["build", "deliver"]


def test_failure_stops_the_pipeline(fake_runners):
    """A failed stage stops everything after it and exits 1.

    Args:
        fake_runners: The recorder fixture.

    Raises:
        AssertionError: If later stages still run.
    """
    fake_runners["behaviour"]["build"] = stages.StageFailed("leak")
    assert cli.main(["--offline"]) == 1
    assert fake_runners["ran"][-1] == "build" and "deliver" not in fake_runners["ran"]
