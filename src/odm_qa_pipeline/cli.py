"""The command line the templates call.

Every subcommand here exists because a workflow step would otherwise have to
hardcode something: a version range, a gate list, or the aggregation rule. Each of
those written into YAML is a second copy that drifts silently.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import RESULT_FORMAT, __version__
from .aggregate import (AggregateError, aggregate, parse_assignment,
                        read_results, render)
from .gates import GATES, names
from .pins import PinsError, describe, requirement, requirements_for, unpinned

EXIT_CLEAN, EXIT_REGRESSION, EXIT_INCOMPLETE = 0, 1, 2


def _pins(args: argparse.Namespace) -> int:
    try:
        if args.component:
            print(requirement(args.component))
            return EXIT_CLEAN
        if args.gate:
            for line in requirements_for(args.gate):
                print(line)
            return EXIT_CLEAN
        if args.json:
            print(json.dumps(describe(), indent=2))
            return EXIT_CLEAN
    except PinsError as error:
        print(str(error), file=sys.stderr)
        return EXIT_INCOMPLETE

    for row in describe():
        marker = " " if row["published"] else "*"
        print(f"{marker} {row['component']:<28} {row['gate']:<12} "
              f"{row['requirement']}")
    loose = unpinned()
    if loose:
        print("\n* not pinned to a version:")
        for name, why in loose.items():
            print(f"    {name}: {why}")
    return EXIT_CLEAN


def _gates(args: argparse.Namespace) -> int:
    if args.json:
        print(json.dumps([{"name": g.name, "question": g.question,
                           "supplied_by": list(g.supplied_by),
                           "regression_means": g.regression_means}
                          for g in GATES], indent=2))
        return EXIT_CLEAN
    for index, gate in enumerate(GATES, start=1):
        print(f"{index}. {gate.name}")
        print(f"     asks: {gate.question}")
        print(f"     from: {', '.join(gate.supplied_by)}")
        print(f"     a non-zero exit means: {gate.regression_means}")
    return EXIT_CLEAN


def _aggregate(args: argparse.Namespace) -> int:
    try:
        results = list(read_results(args.results)) if args.results else []
        results.extend(parse_assignment(text) for text in (args.gate or []))
        summary = aggregate(results, expected=args.expect or None,
                            optional=args.optional or ())
    except AggregateError as error:
        # The aggregation itself failing is could-not-complete, not clean. This
        # is the one place where getting the exit code wrong would invert the
        # whole point of the tool.
        print(f"could not aggregate: {error}", file=sys.stderr)
        return EXIT_INCOMPLETE

    print(render(summary))
    loose = unpinned()
    if loose:
        # Said out loud on every run. A pipeline whose inputs can change between
        # two identical invocations should not keep that in a file nobody opens.
        print("  note: " + ", ".join(loose) + " track a branch, not a version")

    if args.out:
        Path(args.out).write_text(json.dumps(summary, indent=2) + "\n",
                                  encoding="utf-8")
    return summary["exit_code"]


def _record(args: argparse.Namespace) -> int:
    """Write one gate's result, so a shell step does not hand-write JSON."""
    if args.gate not in names():
        print(f"no gate named {args.gate!r}; this pipeline runs "
              f"{', '.join(names())}", file=sys.stderr)
        return EXIT_INCOMPLETE
    payload = {"format": RESULT_FORMAT, "gate": args.gate,
               "exit_code": args.exit_code, "detail": args.detail or ""}
    if args.artifact:
        payload["artifact"] = args.artifact
    Path(args.out).write_text(json.dumps(payload, indent=2) + "\n",
                              encoding="utf-8")
    return EXIT_CLEAN


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="odm-qa-pipeline",
        description="Compose the ODM QA gates and aggregate one verdict.")
    parser.add_argument("--version", action="version",
                        version=f"odm-qa-pipeline {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    pins = sub.add_parser("pins", help="the version constraints, from one file")
    pins.add_argument("--component", help="print one component's requirement")
    pins.add_argument("--gate", help="print every requirement a gate needs")
    pins.add_argument("--json", action="store_true")
    pins.set_defaults(handler=_pins)

    gates = sub.add_parser("gates", help="the gates, in the order they run")
    gates.add_argument("--json", action="store_true")
    gates.set_defaults(handler=_gates)

    record = sub.add_parser("record", help="write one gate-result document")
    record.add_argument("--gate", required=True)
    record.add_argument("--exit-code", type=int, required=True)
    record.add_argument("--detail")
    record.add_argument("--artifact")
    record.add_argument("--out", required=True)
    record.set_defaults(handler=_record)

    agg = sub.add_parser("aggregate", help="one verdict from every gate")
    agg.add_argument("--results", help="directory of gate-result documents")
    agg.add_argument("--gate", action="append",
                     help="name=code, repeatable; e.g. coverage=1")
    agg.add_argument("--expect", action="append",
                     help="gate that must report; defaults to all four")
    agg.add_argument("--optional", action="append",
                     help="gate declared optional for this pipeline")
    agg.add_argument("--out", help="write the summary JSON here")
    agg.set_defaults(handler=_aggregate)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":                                   # pragma: no cover
    sys.exit(main())
