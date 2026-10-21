"""Command line for the generation layer.

Usage, from the project root:
    .venv/Scripts/python -m generate libraries                              # seed libraries from the split plan
    .venv/Scripts/python -m generate proact --run proact-v1 [--limit 20]    # locate ATBench boundaries
    .venv/Scripts/python -m generate proact-sheet --run proact-v1           # human check sheet (CSV)
    .venv/Scripts/python -m generate proact-import --run proact-v1 [--sheet filled.csv]
    .venv/Scripts/python -m generate proact-gate --run proact-v1            # Gate P
    .venv/Scripts/python -m generate inject --run inject-mvp --side train --groups 50
    .venv/Scripts/python -m generate review-sheet --run inject-mvp [--sample 200]
    .venv/Scripts/python -m generate review-import --run inject-mvp --sheet filled.csv
    .venv/Scripts/python -m generate review-gate --run inject-mvp           # Gate 1 / Gate 2
A run stopped by a daily quota exits with code 3; run the same command again later to resume.
"""
import argparse
import json
import sys

from . import inject, libraries, proact, review


def main(argv=None) -> int:
    """Parse the command line and run one command.

    Args:
        argv: Arguments; None uses sys.argv.

    Returns:
        Exit code: 0 on success, 3 if a run stopped on a quota (resume later).
    """
    parser = argparse.ArgumentParser(prog="python -m generate", description="Generation and annotation layer.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("libraries", help="build seed libraries from the split plan")
    for name in ("proact", "proact-sheet", "proact-import", "proact-gate"):
        p = sub.add_parser(name)
        p.add_argument("--run", required=True)
        if name == "proact":
            p.add_argument("--limit", type=int, default=None, help="judge at most this many unsafe runs")
        if name == "proact-import":
            p.add_argument("--sheet", default=None)
    p = sub.add_parser("inject")
    p.add_argument("--run", required=True)
    p.add_argument("--side", choices=("train", "diagnostic"), default="train")
    p.add_argument("--groups", type=int, required=True)
    for name in ("review-sheet", "review-import", "review-gate"):
        p = sub.add_parser(name)
        p.add_argument("--run", required=True)
        if name == "review-sheet":
            p.add_argument("--sample", type=int, default=None)
            p.add_argument("--include-rejected", action="store_true")
        if name == "review-import":
            p.add_argument("--sheet", required=True)
    args = parser.parse_args(argv)

    if args.command == "libraries":
        result = libraries.build()
    elif args.command == "proact":
        result = proact.locate(args.run, args.limit)
    elif args.command == "proact-sheet":
        result = proact.write_sheet(args.run)
    elif args.command == "proact-import":
        result = proact.import_sheet(args.run, args.sheet)
    elif args.command == "proact-gate":
        result = proact.gate(args.run)
    elif args.command == "inject":
        result = inject.generate(args.run, args.side, args.groups)
    elif args.command == "review-sheet":
        result = review.write_sheet(args.run, args.sample, args.include_rejected)
    elif args.command == "review-import":
        result = review.import_sheet(args.run, args.sheet)
    else:
        result = review.gate(args.run)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if isinstance(result, dict) and result.get("stopped"):
        print(f"stopped: {result['stopped']}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
