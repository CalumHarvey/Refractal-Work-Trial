"""The pipeline's stages. Each calls the existing package that does the work and returns a short status.

A stage that stops on a model's daily quota raises QuotaStop; the runner decides whether the remaining
stages go on (config `on_quota`).
"""
from dataclasses import dataclass, field

from ingest.common.manifest import processed_state
from ingest.common.paths import has_input

STAGES = ("convert", "plan_splits", "libraries", "proact", "generate", "build", "deliver", "experiment")
MODEL_STAGES = ("proact", "generate")


class QuotaStop(RuntimeError):
    """Raised when a model stage stopped on a daily quota (its progress is saved; re-run to resume)."""


class StageFailed(RuntimeError):
    """Raised when a stage cannot complete (e.g. stale inputs, conversion issues, Jev rejected a request)."""


@dataclass
class Settings:
    """Everything the stages need, from config/pipeline.yaml plus command-line overrides.

    Attributes:
        proact_run: PROACT run folder.
        proact_limit: Judge at most this many unsafe runs (None = all remaining).
        inject_run: Generation run folder.
        groups: Groups to have per side, e.g. {"train": 50, "diagnostic": 0}.
        deliver_run: Delivery folder name (None = timestamp).
        dry_run: Delivery dry-run override (None = config/deliver.yaml).
        selection: deliver.selection.Selection, or None for config/deliver.yaml.
        seeds: Experiment seeds.
        reference: Rows per licensed set for the Gemini reference (0 = skip).
    """

    proact_run: str
    proact_limit: int | None
    inject_run: str
    groups: dict = field(default_factory=dict)
    deliver_run: str | None = None
    dry_run: bool | None = None
    selection: object = None
    seeds: int = 3
    reference: int = 0


def convert(settings: Settings) -> dict:
    """Convert every dataset whose processed output is missing or stale (and whose input exists).

    Args:
        settings: Pipeline settings (unused).

    Returns:
        `{"converted": [...], "current": n, "skipped_no_input": [...]}`.

    Raises:
        StageFailed: If a conversion had rejects or failed reconciliation checks.
    """
    from ingest.run import available_datasets, run_one

    converted, current, skipped, failed = [], 0, [], []
    for dataset in available_datasets():
        if not has_input(dataset):
            skipped.append(dataset)
            continue
        if processed_state(dataset)["state"] == "current":
            current += 1
            continue
        (converted if run_one(dataset) else failed).append(dataset)
    if failed:
        raise StageFailed(f"conversion issues in {failed} (see data/processed/<dataset>/report.json)")
    return {"converted": converted, "current": current, "skipped_no_input": skipped}


def plan_splits(settings: Settings) -> dict:
    """Freeze the real-data splits (data/splits/plan.json).

    Args:
        settings: Pipeline settings (unused).

    Returns:
        `{"exit": 0}`.

    Raises:
        StageFailed: If the build inputs are not usable.
    """
    from ingest.build import main as build_main

    if build_main(["--plan-splits"]) != 0:
        raise StageFailed("plan_splits failed")
    return {"exit": 0}


def libraries(settings: Settings) -> dict:
    """Build the seed libraries from the split plan.

    Args:
        settings: Pipeline settings (unused).

    Returns:
        Library sizes per side.
    """
    from generate import libraries as libs

    return {side: {"contexts": s["contexts"], "attacks": s["attacks"]} for side, s in libs.build().items()}


def proact(settings: Settings) -> dict:
    """Locate PROACT boundaries (resumes an existing run).

    Args:
        settings: Pipeline settings (proact_run, proact_limit).

    Returns:
        Counts by method.

    Raises:
        QuotaStop: If a daily quota ran out.
    """
    from generate import proact as pro

    result = pro.locate(settings.proact_run, settings.proact_limit)
    if result.get("stopped"):
        raise QuotaStop(result["stopped"])
    return {"by_method": result["by_method"]}


def generate(settings: Settings) -> dict:
    """Generate synthetic injection groups up to the configured number per side (resumes the run).

    Args:
        settings: Pipeline settings (inject_run, groups).

    Returns:
        Groups, kept and yield per side.

    Raises:
        QuotaStop: If a daily quota ran out.
    """
    from generate import inject

    out = {}
    for side, n in settings.groups.items():
        if not n:
            continue
        result = inject.generate(settings.inject_run, side, n)
        out[side] = {"groups": result["groups"], "kept": result["kept"], "yield": result["yield"]}
        if result.get("stopped"):
            raise QuotaStop(result["stopped"])
    return out


def build(settings: Settings) -> dict:
    """Convert whatever changed (e.g. new PROACT or generated runs), then build data/training/ and data/jev/.

    Args:
        settings: Pipeline settings (unused).

    Returns:
        The conversion summary and split counts by data kind.

    Raises:
        StageFailed: If the build fails or finds leaking group keys.
    """
    import json

    from ingest.build import main as build_main
    from ingest.common.paths import TRAINING

    converted = convert(settings)
    if build_main([]) != 0:
        raise StageFailed("build failed (see the messages above and data/training/report.json)")
    report = json.loads((TRAINING / "report.json").read_text(encoding="utf-8"))
    return {"converted": converted["converted"],
            "by_kind": {name: s["by_kind"] for name, s in report["splits"].items() if s["total"]}}


def deliver(settings: Settings) -> dict:
    """Select and deliver data/jev to Jev.

    Args:
        settings: Pipeline settings (deliver_run, dry_run, selection).

    Returns:
        Run name, dry-run flag and traces sent per split.

    Raises:
        StageFailed: If data/jev is stale or Jev rejected a request.
    """
    from deliver.client import JevError
    from deliver.delivery import StaleBuild, run

    try:
        manifest = run(settings.deliver_run, settings.selection, settings.dry_run)
    except (StaleBuild, JevError) as exc:
        raise StageFailed(str(exc)) from exc
    return {"run": manifest["run"], "dry_run": manifest["dry_run"],
            "traces": {s: v["traces"] for s, v in manifest["sent"].items()}}


def experiment(settings: Settings) -> dict:
    """Run the MVP experiment on the current training view.

    Args:
        settings: Pipeline settings (seeds, reference).

    Returns:
        `{"exit": 0}` (the report path is printed by the experiment).
    """
    from experiments.mvp.run import main as experiment_main

    return {"exit": experiment_main(["--seeds", str(settings.seeds), "--reference", str(settings.reference)])}


RUNNERS = {"convert": convert, "plan_splits": plan_splits, "libraries": libraries, "proact": proact,
           "generate": generate, "build": build, "deliver": deliver, "experiment": experiment}
