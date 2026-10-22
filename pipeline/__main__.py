"""Run the whole pipeline with one command.

Usage, from the project root:
    .venv/Scripts/python -m pipeline                                   # the stages in config/pipeline.yaml
    .venv/Scripts/python -m pipeline --offline                         # no model calls (skips proact, generate)
    .venv/Scripts/python -m pipeline --stages build deliver            # only these stages (always in pipeline order)
    .venv/Scripts/python -m pipeline --from build                      # this stage and every later configured stage
    .venv/Scripts/python -m pipeline --groups 200 --kinds real synthetic --send
    .venv/Scripts/python -m pipeline --list                            # show the stages that would run

Exit codes: 0 done; 1 a stage failed; 3 a model stage stopped on a daily quota (re-run later to resume).
"""
import argparse
import json
import sys
from functools import lru_cache

import yaml

from deliver.__main__ import add_selection_arguments, selection_from
from generate.logs import configure, level_from
from ingest.common.paths import ROOT

from .stages import MODEL_STAGES, RUNNERS, STAGES, QuotaStop, Settings, StageFailed

CONFIG_FILE = ROOT / "config" / "pipeline.yaml"


@lru_cache(maxsize=1)
def pipeline_config() -> dict:
    """Load config/pipeline.yaml (cached after the first call).

    Returns:
        The parsed configuration.
    """
    return yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))


def parse(argv=None) -> argparse.Namespace:
    """Parse the command line.

    Args:
        argv: Arguments; None uses sys.argv.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(prog="python -m pipeline", description="Run the whole data pipeline.")
    which = parser.add_argument_group("which stages")
    which.add_argument("--stages", nargs="+", choices=STAGES, help="run only these stages (in pipeline order)")
    which.add_argument("--from", dest="start", choices=STAGES, help="start at this stage")
    which.add_argument("--skip", nargs="+", choices=STAGES, default=[], help="leave these stages out")
    which.add_argument("--offline", action="store_true", help=f"no model calls: skip {', '.join(MODEL_STAGES)}")
    which.add_argument("--experiment", action="store_true", help="also run the MVP experiment at the end")
    which.add_argument("--list", action="store_true", help="print the stages that would run, and stop")
    which.add_argument("-v", "--verbose", action="store_true", help="log every model call (cache hits, call times)")
    which.add_argument("-q", "--quiet", action="store_true", help="log warnings and errors only")
    models = parser.add_argument_group("model stages")
    models.add_argument("--proact-run", help="PROACT run folder (default: config)")
    models.add_argument("--proact-limit", type=int, help="judge at most this many unsafe ATBench runs")
    models.add_argument("--proact-split", choices=("train", "test"), help="judge only ATBench runs on this split")
    models.add_argument("--inject-run", help="generation run folder (default: config)")
    models.add_argument("--groups", type=int, help="train-side groups to have in the generation run")
    models.add_argument("--diagnostic-groups", type=int, help="diagnostic-side groups to have")
    deliver = parser.add_argument_group("delivery to Jev")
    deliver.add_argument("--deliver-run", help="delivery folder name (default: a timestamp)")
    mode = deliver.add_mutually_exclusive_group()
    mode.add_argument("--send", action="store_true", help="POST to Jev (overrides the dry-run setting)")
    mode.add_argument("--dry-run", action="store_true", help="write the requests only")
    add_selection_arguments(deliver)
    exp = parser.add_argument_group("experiment")
    exp.add_argument("--seeds", type=int, help="experiment seeds (default: config)")
    return parser.parse_args(argv)


def stages_to_run(args: argparse.Namespace) -> list[str]:
    """Work out which stages run, in pipeline order.

    Args:
        args: Parsed arguments.

    Returns:
        Stage names.
    """
    chosen = list(args.stages or pipeline_config()["stages"])
    if args.experiment and "experiment" not in chosen:
        chosen.append("experiment")
    if args.start:
        chosen = [s for s in chosen if STAGES.index(s) >= STAGES.index(args.start)]
    skip = set(args.skip) | (set(MODEL_STAGES) if args.offline else set())
    return [s for s in STAGES if s in chosen and s not in skip]


def settings_from(args: argparse.Namespace) -> Settings:
    """Combine config/pipeline.yaml with command-line overrides.

    Args:
        args: Parsed arguments.

    Returns:
        The stage settings.
    """
    cfg = pipeline_config()
    groups = dict(cfg["generate"]["groups"])
    if args.groups is not None:
        groups["train"] = args.groups
    if args.diagnostic_groups is not None:
        groups["diagnostic"] = args.diagnostic_groups
    dry_run = False if args.send else True if args.dry_run else cfg["deliver"]["dry_run"]
    return Settings(proact_run=args.proact_run or cfg["proact"]["run"],
                    proact_limit=args.proact_limit if args.proact_limit is not None else cfg["proact"]["limit"],
                    proact_split=args.proact_split or cfg["proact"].get("split"),
                    inject_run=args.inject_run or cfg["generate"]["run"], groups=groups,
                    deliver_run=args.deliver_run or cfg["deliver"]["run"], dry_run=dry_run,
                    selection=selection_from(args),
                    seeds=args.seeds or cfg["experiment"]["seeds"], reference=cfg["experiment"]["reference"])


def main(argv=None) -> int:
    """Run the selected stages in order and print a summary.

    Args:
        argv: Arguments; None uses sys.argv.

    Returns:
        Exit code: 0 done, 1 a stage failed, 3 a model stage stopped on a quota.
    """
    args = parse(argv)
    stages = stages_to_run(args)
    if args.list:
        print(" -> ".join(stages))
        return 0
    settings = settings_from(args)
    configure(level_from(args.verbose, args.quiet))
    on_quota = pipeline_config().get("on_quota", "continue")
    summary, code, quota_hit = {}, 0, False
    for stage in stages:
        if quota_hit and stage in MODEL_STAGES:
            summary[stage] = {"status": "skipped (quota)"}
            continue
        print(f"== {stage}", file=sys.stderr)
        try:
            summary[stage] = {"status": "done", **RUNNERS[stage](settings)}
        except QuotaStop as exc:
            summary[stage] = {"status": "stopped on quota", "detail": str(exc)[:200]}
            quota_hit, code = True, 3
            if on_quota == "stop":
                break
        except (StageFailed, ValueError, FileNotFoundError) as exc:
            summary[stage] = {"status": "failed", "detail": str(exc)[:300]}
            code = 1
            break
        except OSError as exc:  # e.g. a file still locked by OneDrive after the retries
            summary[stage] = {"status": "failed", "detail": f"{exc} (a file may be locked by a sync client; "
                                                            f"re-run with --from {stage})"}
            code = 1
            break
    print(json.dumps(summary, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
