"""Score gate 1 from what the DMTF validators wrote, not from whether a file exists.

Gate 1 is the one gate this suite does not own, and it was scored by a heuristic:
any file in the log directory meant *the validator ran and disagreed*, no file
meant *it never got that far*. That is wrong, it is wrong in the direction that
matters, and the reason is invisible from outside the validators.

Derived by installing the pinned versions and reading them. Not from their
documentation, which does not state any of this:

  redfish-service-validator 3.1.6
    console_scripts.py:133   logdir/<YYYY-MM-DD-HHMMSS>/ is created FIRST
    console_scripts.py:141   the debug log is written into it BEFORE the service
                             is contacted
    console_scripts.py:163   a service it cannot set up returns (1, None)
    console_scripts.py:191   a completed run returns (int(fail_count > 0), report)
    report.py:293            the report is RedfishServiceValidatorReport_*.html
    -- and there is no JSON output at all.

  redfish-protocol-validator 1.3.1
    console_scripts.py:161-167  setup failures sys.exit(1) having written nothing
    console_scripts.py:219      a completed run always writes results.json
    console_scripts.py:225      then exits int(fail_count > 0)
    report.py:169-193           results.json carries TestResults -> <suite> ->
                                {pass, fail, skip, warn}

**So a service validator that cannot reach the BMC exits 1 and leaves a debug log
in the directory.** The old rule looked in that directory, found a file, and
recorded gate 1 as a regression against the machine: a `2` reported as a `1`,
which is the one inversion this whole pipeline exists to prevent, sitting in the
gate it borrowed rather than built.

The protocol half is now a reading -- counts, out of the file the tool wrote. The
service half is still a discrimination, because that tool publishes no
machine-readable verdict; the results file is the best available evidence that it
reached the end, and this says so rather than implying more.

Two rules hold throughout. Only `0` and `1` are verdicts from these tools, because
those are the only values their code returns; anything else is a foreign exit --
`127` from a missing command, `2` from argparse -- and reads as could-not-complete
with the raw number kept beside it, exactly as `aggregate.py` treats a gate. And
where a file is not the shape these versions write, the answer is `2`: a reader
that guesses at an unrecognised shape is worth less than one that admits the
shape changed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CLEAN, REGRESSION, INCOMPLETE = 0, 1, 2

# report.py:293 -- the service validator's results file, inside a timestamped
# subdirectory of the log directory, which is why nothing here globs one level.
SERVICE_REPORT = "RedfishServiceValidatorReport_*.html"

# report.py:170 -- the protocol validator's machine-readable results.
PROTOCOL_RESULTS = "results.json"

# The versions these shapes were read out of. Quoted in the detail line when a
# shape does not match, so the reader is told which claim just went stale.
DERIVED_FROM = ("redfish-service-validator 3.1.6",
                "redfish-protocol-validator 1.3.1")


@dataclass(frozen=True)
class Verdict:
    exit_code: int
    detail: str


def _foreign(name: str, code: int) -> Verdict | None:
    """Anything outside {0, 1} never came from the validator's own return."""
    if code in (CLEAN, REGRESSION):
        return None
    return Verdict(INCOMPLETE,
                   f"{name} exited {code}, which is not a verdict it can return; "
                   f"treating it as could not complete")


def _service(logdir: Path, code: int | None) -> Verdict:
    if code is None:
        return Verdict(INCOMPLETE,
                       "the service validator was not run, and half of "
                       "conformance is not an answer to gate 1")
    foreign = _foreign("the service validator", code)
    if foreign:
        return foreign
    reports = sorted(logdir.rglob(SERVICE_REPORT))
    if not reports:
        return Verdict(INCOMPLETE,
                       f"the service validator exited {code} and wrote no "
                       f"report; it did not reach a verdict, and the debug log "
                       f"beside it is not one")
    where = reports[-1].name
    if code == CLEAN:
        return Verdict(CLEAN, f"the service validator ran clean ({where})")
    return Verdict(REGRESSION,
                   f"the service validator ran and found non-conformance "
                   f"({where})")


def _protocol(logdir: Path, code: int | None) -> Verdict:
    if code is None:
        return Verdict(INCOMPLETE,
                       "the protocol validator was not run, and half of "
                       "conformance is not an answer to gate 1")
    foreign = _foreign("the protocol validator", code)
    if foreign:
        return foreign
    found = sorted(logdir.rglob(PROTOCOL_RESULTS))
    if not found:
        return Verdict(INCOMPLETE,
                       f"the protocol validator exited {code} and wrote no "
                       f"{PROTOCOL_RESULTS}; it did not reach a verdict")
    try:
        results = json.loads(found[-1].read_text(encoding="utf-8"))
        suites = results["TestResults"]
        counted = [(name, body) for name, body in suites.items()
                   if isinstance(body, dict) and "fail" in body]
        if not counted:
            raise KeyError("no suite carrying a fail count")
        failed = sum(int(body["fail"]) for _, body in counted)
        passed = sum(int(body.get("pass", 0)) for _, body in counted)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return Verdict(INCOMPLETE,
                       f"{found[-1].name} is not the shape "
                       f"{DERIVED_FROM[1]} writes ({error}); this reader no "
                       f"longer describes the tool, so nothing is claimed")

    # console_scripts.py:225 ties the exit code to the fail count. If they
    # disagree, the tool changed its rule and this file is describing a version
    # that is no longer installed -- which is a thing to report, not to resolve.
    if (failed > 0) != (code == REGRESSION):
        return Verdict(INCOMPLETE,
                       f"the protocol validator exited {code} while its results "
                       f"record {failed} failure(s); {DERIVED_FROM[1]} ties one "
                       f"to the other, so this reader is out of date")

    if failed:
        return Verdict(REGRESSION,
                       f"the protocol validator recorded {failed} failure(s) "
                       f"over {passed + failed} check(s)")
    return Verdict(CLEAN,
                   f"the protocol validator recorded no failures over "
                   f"{passed} check(s)")


def read(logdir, service_exit: int | None,
         protocol_exit: int | None) -> Verdict:
    """One verdict for gate 1, by `max`, the same precedence as everywhere else."""
    directory = Path(logdir)
    if not directory.is_dir():
        return Verdict(INCOMPLETE,
                       f"{logdir} is not a directory; neither validator can "
                       f"have written anything there")
    halves = (_service(directory, service_exit),
              _protocol(directory, protocol_exit))
    return Verdict(max(half.exit_code for half in halves),
                   "\n".join(f"  {half.detail}" for half in halves))
