"""Command line for delivery to Jev.

Usage, from the project root (after ingest/build.py):
    .venv/Scripts/python -m deliver                                   # config/deliver.yaml as it stands (dry run)
    .venv/Scripts/python -m deliver --kinds real relabelled_real      # leave synthetic data out
    .venv/Scripts/python -m deliver --splits train --exclude toolace  # one split, one dataset left out
    .venv/Scripts/python -m deliver --send                            # actually POST to the configured endpoint
"""
import argparse
import json
import sys

from ingest.assembly.config import DATA_KINDS
from ingest.assembly.split import SPLITS

from .client import JevError
from .delivery import StaleBuild, run
from .selection import Selection


def add_selection_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the selection flags (shared with the pipeline command).

    Args:
        parser: The parser to extend.

    Returns:
        None.
    """
    parser.add_argument("--splits", nargs="+", choices=SPLITS, help="splits to send (default: config)")
    parser.add_argument("--kinds", nargs="+", choices=DATA_KINDS, help="data kinds to send (default: config)")
    parser.add_argument("--include", nargs="+", metavar="DATASET", help="send only these datasets")
    parser.add_argument("--exclude", nargs="+", metavar="DATASET", help="never send these datasets")


def selection_from(args: argparse.Namespace) -> Selection:
    """Build a selection from parsed flags over the config defaults.

    Args:
        args: Parsed arguments carrying splits, kinds, include, exclude.

    Returns:
        The selection.
    """
    return Selection.from_config(splits=args.splits, kinds=args.kinds, include=args.include, exclude=args.exclude)


def main(argv=None) -> int:
    """Parse the command line and run one delivery.

    Args:
        argv: Arguments; None uses sys.argv.

    Returns:
        Exit code: 0 on success, 1 if data/jev is stale or Jev rejected a request.
    """
    parser = argparse.ArgumentParser(prog="python -m deliver", description="Select data and deliver it to Jev.")
    parser.add_argument("--run", help="delivery folder name (default: a timestamp)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--send", action="store_true", help="POST to the endpoint (overrides api.dry_run)")
    mode.add_argument("--dry-run", action="store_true", help="write request bodies only (overrides api.dry_run)")
    add_selection_arguments(parser)
    args = parser.parse_args(argv)
    dry_run = False if args.send else True if args.dry_run else None
    try:
        manifest = run(args.run, selection_from(args), dry_run)
    except (StaleBuild, JevError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(json.dumps({k: manifest[k] for k in ("run", "dry_run", "selection", "sent")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
