"""Find and exercise the scenarios an orchestrator checkout ships.

**Nothing here names a path, a file or a domain.** The three canaries that use
this used to name `scenarios/stuck-at.yaml` and `scenarios/` in workflow YAML,
which made this pipeline depend on where another repository keeps its files. That
is a dependency nothing type-checks: the day those files move, the canary reports
a broken seam when the seam is fine, or worse, finds nothing and says so quietly.

So a scenario is found by its **format marker** -- the thing the file declares
about itself -- and the set worth running is the set this build **can name**,
which is a question the orchestrator answers through `check`. A scenario written
for a vertical whose plugin is not installed is correctly out of scope rather than
a failure; a checkout that offers no runnable scenario at all is a broken seam and
exits 2, because a canary that silently checks nothing is worse than no canary.

The exit codes are the family's, and `2` never reads as clean.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

EXIT_CLEAN, EXIT_REGRESSION, EXIT_INCOMPLETE = 0, 1, 2

#: What a scenario says about itself. Matched at the start of a line so a mention
#: inside prose or a comment is not a scenario -- the same reason the orchestrator
#: matches its own content handles by shape rather than by the label beside them.
MARKER = re.compile(r"^format:\s*qa-scenario/", re.MULTILINE)

#: Suffixes worth opening. Not a claim about the format -- the marker decides that
#: -- only a bound on how much of a checkout gets read.
SUFFIXES = (".yaml", ".yml")


class ScenarioError(RuntimeError):
    """The checkout could not be exercised. Distinct from a scenario failing."""


@dataclass(frozen=True)
class Outcome:
    """One scenario, run."""

    path: Path
    exit_code: int
    detail: str = ""


@dataclass(frozen=True)
class Report:
    """What a checkout offered, and what happened to it."""

    root: Path
    found: tuple[Path, ...]
    in_scope: tuple[Path, ...]
    out_of_scope: tuple[Path, ...]
    ran: tuple[Outcome, ...]

    @property
    def exit_code(self) -> int:
        if not self.in_scope:
            return EXIT_INCOMPLETE
        if any(o.exit_code == EXIT_INCOMPLETE for o in self.ran):
            return EXIT_INCOMPLETE
        if any(o.exit_code != EXIT_CLEAN for o in self.ran):
            return EXIT_REGRESSION
        return EXIT_CLEAN

    def render(self) -> str:
        lines = [f"{len(self.found)} scenario(s) under {self.root}, "
                 f"{len(self.in_scope)} this build can name"]
        for path in self.out_of_scope:
            lines.append(f"  out of scope  {self._name(path)}  "
                         f"(names something this build has not loaded)")
        for outcome in self.ran:
            word = {EXIT_CLEAN: "ok", EXIT_REGRESSION: "MISMATCH",
                    EXIT_INCOMPLETE: "COULD NOT COMPLETE"}.get(
                        outcome.exit_code, f"exit {outcome.exit_code}")
            lines.append(f"  {word:<20} {self._name(outcome.path)}")
            if outcome.exit_code != EXIT_CLEAN and outcome.detail:
                lines.append(f"      {outcome.detail.strip()[:300]}")
        if not self.in_scope:
            lines.append("  nothing this build can name; the seam was not "
                         "exercised, which is not the same as a clean one")
        return "\n".join(lines)

    def _name(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)


def _shell(argv: Sequence[str]) -> subprocess.CompletedProcess:
    """Run it, and turn *no such program* into a refusal rather than a traceback.

    A canary whose tool is missing has checked nothing. Saying so in prose and
    exiting 2 is the contract; a stack trace is a check that fell over while
    looking like a bug in this file.
    """
    try:
        return subprocess.run(list(argv), capture_output=True, text=True,
                              timeout=900)
    except FileNotFoundError as missing:
        raise ScenarioError(
            f"{argv[0]!r} is not on PATH, so nothing was exercised: {missing}"
        ) from missing
    except subprocess.TimeoutExpired as slow:
        raise ScenarioError(f"{' '.join(argv)} did not finish: {slow}") from slow


def discover(root: Path) -> tuple[Path, ...]:
    """Every file under `root` that declares itself a scenario.

    Sorted, so two runs over one checkout report in the same order and a diff of
    two canary logs is about the scenarios rather than about the walk.
    """
    root = Path(root)
    if not root.is_dir():
        raise ScenarioError(f"{root} is not a directory; nothing to exercise")
    found = []
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if MARKER.search(text):
            found.append(path)
    return tuple(found)


def exercise(root: Path, *, tool: str | Sequence[str] = "qa-orchestrator",
             run: Callable[[Sequence[str]], subprocess.CompletedProcess] | None = None,
             ) -> Report:
    """Check every scenario found, then run the ones this build can name.

    `check` is the scope question and the parse question at once: a scenario this
    build cannot name is refused by it, and so is a malformed one. Those are
    different facts and this cannot tell them apart -- which is why a checkout
    where NOTHING is in scope exits 2 rather than passing with an empty set.
    """
    runner = run or _shell
    # A command, not necessarily one word: pointing this at a build that is not
    # installed (`python3 -m qa_orchestrator.cli`) is how it gets tested at all.
    argv0 = list(tool) if not isinstance(tool, str) else shlex.split(tool)
    if not argv0:
        raise ScenarioError("no orchestrator command given")
    root = Path(root)
    found = discover(root)

    in_scope, out_of_scope = [], []
    for path in found:
        result = runner([*argv0, "check", str(path)])
        if result.returncode == EXIT_CLEAN:
            in_scope.append(path)
        elif result.returncode == EXIT_INCOMPLETE:
            # The tool answered, and refused. Whether it refused because this
            # build cannot name what the scenario asks for or because the file
            # is malformed, `check` reports both the same way and this cannot
            # tell them apart -- which is why an empty in-scope set is exit 2.
            out_of_scope.append(path)
        else:
            # It did NOT answer: an unimportable build exits 1, a missing one
            # 127. Filing that under *out of scope* would name the scenario for
            # a fault in the tool -- a check firing precisely at the wrong
            # subject, which is worse than one that stays quiet.
            raise ScenarioError(
                f"{argv0[0]!r} exited {result.returncode} on {path}, which is "
                f"outside its documented 0/1/2 interface, so nothing here was "
                f"checked: "
                f"{(result.stderr or result.stdout or '').strip()[:300]}")

    ran = []
    for path in in_scope:
        result = runner([*argv0, "run", str(path)])
        detail = (result.stderr or result.stdout or "")
        ran.append(Outcome(path=path, exit_code=result.returncode, detail=detail))

    return Report(root=root, found=found, in_scope=tuple(in_scope),
                  out_of_scope=tuple(out_of_scope), ran=tuple(ran))
