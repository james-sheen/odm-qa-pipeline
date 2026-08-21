"""One exit code from four, under the rule that matters.

`0` clean, `1` regressions, `2` could not complete -- the same three the audit tool
and the orchestrator use, and deliberately not a fourth vocabulary for one set of
numbers. Precedence is `max`, copied rather than reasoned out afresh: when a run
both found a regression and failed to finish, the answer is `2`, because `2` is the
statement about the denominator and `1` would let a reader conclude the rest was
checked.

## The thing only this layer can notice

A gate that never ran reports nothing. Not zero -- nothing. Every individual tool
in this suite is careful about could-not-complete, and not one of them can tell you
it was never invoked, because a program that did not start emits no exit code at
all. Somebody has to hold the list of what was supposed to happen and compare.

That is this module, and it is the reason the umbrella is a program rather than a
YAML file. **A missing gate is `2`.** A pipeline where the injection step was
commented out six weeks ago and every run since came back green is the exact
failure this exists to prevent.

## An exit code nobody defined

A gate that dies on `command not found` exits `127`. Taking `max` over raw codes
would return `127` -- non-zero, so a CI job would still fail, and the summary would
report a number from a vocabulary this suite does not use. Anything outside
`{0, 1, 2}` is normalised to `2` and the raw code is kept beside it, because
"exited 127" is the useful half of that sentence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import RESULT_FORMAT, SUMMARY_FORMAT
from .gates import names as gate_names

__all__ = ["VERDICTS", "GateResult", "AggregateError", "aggregate",
           "read_results", "parse_assignment"]

# One vocabulary for one set of numbers. The sibling repository grew a second one
# privately -- "could not complete" beside "incomplete" -- and the two disagreed
# from the moment both existed.
VERDICTS = {0: "clean", 1: "regressions", 2: "incomplete"}

CLEAN, REGRESSIONS, INCOMPLETE = 0, 1, 2


class AggregateError(ValueError):
    """The results cannot be aggregated at all."""


@dataclass
class GateResult:
    gate: str
    exit_code: int
    detail: str = ""
    artifact: str | None = None
    #: The code as the tool actually returned it, before normalisation.
    raw_exit_code: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.exit_code, int) or isinstance(self.exit_code, bool):
            raise AggregateError(
                f"{self.gate}: exit_code is {self.exit_code!r}, not an integer")
        if self.exit_code not in VERDICTS:
            self.raw_exit_code = self.exit_code
            self.exit_code = INCOMPLETE
            note = (f"exited {self.raw_exit_code}, which is not one of "
                    f"0/1/2; read as incomplete")
            self.detail = f"{self.detail}; {note}" if self.detail else note

    def to_dict(self) -> dict[str, Any]:
        row = {"gate": self.gate, "exit_code": self.exit_code,
               "verdict": VERDICTS[self.exit_code], "detail": self.detail}
        if self.raw_exit_code is not None:
            row["raw_exit_code"] = self.raw_exit_code
        if self.artifact:
            row["artifact"] = self.artifact
        return row


def parse_assignment(text: str) -> GateResult:
    """`coverage=1` or `coverage=1:some detail` from a shell."""
    name, _, rest = text.partition("=")
    if not _:
        raise AggregateError(
            f"{text!r} is not name=code; write for example coverage=1")
    code, _, detail = rest.partition(":")
    try:
        return GateResult(gate=name.strip(), exit_code=int(code.strip()),
                          detail=detail.strip())
    except ValueError as error:
        raise AggregateError(f"{text!r}: {code!r} is not an integer") from error


def read_results(directory: Path | str) -> list[GateResult]:
    """Every `gate-result/1` document in a directory."""
    directory = Path(directory)
    if not directory.is_dir():
        raise AggregateError(f"no results directory at {directory}")

    results: list[GateResult] = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise AggregateError(f"{path.name} is not valid JSON: {error}")
        if payload.get("format") != RESULT_FORMAT:
            raise AggregateError(
                f"{path.name} declares format {payload.get('format')!r}, this "
                f"build reads {RESULT_FORMAT!r}")
        if "gate" not in payload or "exit_code" not in payload:
            raise AggregateError(
                f"{path.name} is missing 'gate' or 'exit_code'")
        results.append(GateResult(gate=payload["gate"],
                                  exit_code=payload["exit_code"],
                                  detail=payload.get("detail", ""),
                                  artifact=payload.get("artifact")))
    return results


def aggregate(results: Iterable[GateResult], *,
              expected: Iterable[str] | None = None,
              optional: Iterable[str] = ()) -> dict[str, Any]:
    """The summary, including the gates that never reported."""
    results = list(results)
    expected = list(expected) if expected is not None else list(gate_names())
    optional = set(optional)

    unknown = sorted({r.gate for r in results} - set(expected))
    if unknown:
        raise AggregateError(
            "result(s) for gate(s) this pipeline does not declare: "
            + ", ".join(unknown) + f"; it runs {', '.join(expected)}")

    seen: dict[str, GateResult] = {}
    for result in results:
        if result.gate in seen:
            # Two answers to one question is not a pass and not a fail; it is a
            # harness that cannot say which run this summary describes.
            raise AggregateError(
                f"two results for gate {result.gate!r}; a summary cannot say "
                f"which run it describes")
        seen[result.gate] = result

    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    skipped: list[str] = []
    for name in expected:
        if name in seen:
            rows.append(seen[name].to_dict())
        elif name in optional:
            # Declared optional in advance, in the pipeline definition. That is a
            # decision on the record, which silence is not.
            skipped.append(name)
            rows.append({"gate": name, "exit_code": CLEAN,
                         "verdict": "not run (declared optional)",
                         "detail": "this gate was declared optional for this "
                                   "pipeline and did not run"})
        else:
            missing.append(name)
            rows.append({"gate": name, "exit_code": INCOMPLETE,
                         "verdict": VERDICTS[INCOMPLETE],
                         "detail": "this gate reported nothing at all. A gate "
                                   "that did not run has not passed"})

    code = max((row["exit_code"] for row in rows), default=CLEAN)
    decided_by = [row["gate"] for row in rows if row["exit_code"] == code
                  and code != CLEAN]

    return {
        "format": SUMMARY_FORMAT,
        "exit_code": code,
        "verdict": VERDICTS[code],
        "decided_by": decided_by,
        "gates": rows,
        "missing": missing,
        "skipped": skipped,
    }


def render(summary: dict[str, Any]) -> str:
    """The summary as an operator reads it in a log."""
    lines = [f"pipeline: {summary['verdict']} (exit {summary['exit_code']})"]
    for row in summary["gates"]:
        lines.append(f"  {row['gate']:<12} {row['verdict']}"
                     + (f" -- {row['detail']}" if row["detail"] else ""))
    if summary["missing"]:
        lines.append("  gates that never reported: "
                     + ", ".join(summary["missing"]))
    if summary["decided_by"]:
        lines.append("  decided by: " + ", ".join(summary["decided_by"]))
    return "\n".join(lines)
