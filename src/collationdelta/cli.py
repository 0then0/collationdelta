"""Command line entry point. Exit codes are part of the v0.1 public contract."""

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .evidence import capture, compare, coverage_text, human_report
from .formats import DeltaError, dump, load, require


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise DeltaError(message)


def parser():
    root = Parser(
        description="Detect string ordering and equality changes before a runtime upgrade."
    )
    root.add_argument("--version", action="version", version=f"CollationDelta {__version__}")
    commands = root.add_subparsers(dest="command", required=True, parser_class=Parser)
    cap = commands.add_parser(
        "capture", help="observe every ordered pair through an executable adapter"
    )
    cap.add_argument("--corpus", required=True, help="corpus JSON file, at most 256 records")
    cap.add_argument("--profile", required=True, help="requested comparison profile JSON file")
    cap.add_argument("--output", required=True, help="capture JSON destination")
    cap.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="whole-process deadline in seconds (default: 30)",
    )
    cap.add_argument("--stdout-limit", type=int, default=16 * 1024 * 1024, help="stdout byte limit")
    cap.add_argument("--stderr-limit", type=int, default=1024 * 1024, help="stderr byte limit")
    cap.add_argument(
        "adapter", nargs=argparse.REMAINDER, help="adapter argv after --; executed without a shell"
    )
    diff = commands.add_parser("compare", help="compare two captures completely offline")
    diff.add_argument("old")
    diff.add_argument("new")
    diff.add_argument("--format", choices=("human", "json"), default="human")
    diff.add_argument("--json-output", help="also save the full versioned JSON report")
    diff.add_argument("--limit", type=int, default=20, help="maximum findings in human output only")
    commands.add_parser("node-adapter", help="print the bundled Intl.Collator adapter path")
    return root


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        if args.command == "node-adapter":
            print(Path(__file__).parent / "adapters" / "node.mjs")
            return 0
        if args.command == "capture":
            adapter = args.adapter[1:] if args.adapter[:1] == ["--"] else args.adapter
            value = capture(
                load(args.corpus),
                load(args.profile),
                adapter,
                timeout=args.timeout,
                stdout_limit=args.stdout_limit,
                stderr_limit=args.stderr_limit,
            )
            dump(args.output, value)
            print(
                f"{'CAPTURED' if value['coverage']['complete'] else 'INCOMPLETE'} | {coverage_text(value['coverage'])}"
            )
            if value["observation"].get("reason"):
                print(json.dumps(value["observation"]["reason"], ensure_ascii=True))
            return 0 if value["coverage"]["complete"] else 2
        require(args.limit >= 0, "human finding limit must be nonnegative")
        report = compare(load(args.old), load(args.new))
        if args.json_output:
            dump(args.json_output, report)
        if args.format == "json":
            json.dump(report, sys.stdout, ensure_ascii=True, sort_keys=True, indent=2)
            print()
        else:
            print(human_report(report, args.limit), end="")
        return {"STABLE": 0, "DRIFT": 1, "INCOMPLETE": 2, "DRIFT_INCOMPLETE": 2}[report["status"]]
    except (DeltaError, OSError, RecursionError) as exc:
        print(f"ERROR: {str(exc)!a}", file=sys.stderr)
        return 3
