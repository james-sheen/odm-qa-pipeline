"""Every gate a run installs must be resolved in the same breath as the others.

`pip install -r A` followed by `pip install -r B` is two independent
resolutions into one environment, and the second is free to move a pin the
first had just placed. Both commands succeed. Nothing goes red. What runs
afterwards is simply not the environment the manifest describes.

That is not a hypothetical: `odm-cert-generator` 0.2.2 requires the referee at
`>=0.3.0`, and while this manifest capped it below that, installing the
coverage gate and then the certificate gate moved the referee two minor
versions past its own pin -- in the canaries here and, four times over, in the
templates this project ships for other people to run. The one job that never
had the defect is the one whose whole subject is *do these pins resolve*,
because it is the only one that resolved them together.

Two tells, and each caught a real instance:

* two DIFFERENT requirements files installed on one execution path;
* a requirements filename carrying a variable, because a name that varies is
  an install per value and so a resolution per value. That is the shape the
  composition job had -- a loop over gates writing `requirements-${gate}.txt`
  -- and counting installs alone cannot see it, since the loop body is one
  line however many times it runs.

A retry of the SAME file is not a violation and must not be read as one: the
composition job installs one file up to six times while an index catches up.

What this cannot see: an `if`/`else` whose arms install different files would
read as one path. Nothing here is written that way, and the tell to add if it
ever is would be the same one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent

# `pip install ... -r <file>`, capturing the file. `--dry-run` is exempt on
# purpose: it resolves and installs nothing, so it cannot move a pin, and
# asking whether every pin resolves TOGETHER is what seam five exists to do.
INSTALL = re.compile(r"pip\s+install\b(?P<flags>[^\n]*?)\s-r\s+(?P<file>[^\s]+)")


def _blocks(path: Path) -> list[tuple[str, str]]:
    """(environment name, shell text) for one shipped definition.

    A GitHub job is an environment; steps within it share one interpreter, so
    they are joined. A file this cannot parse as a workflow is treated as a
    single environment, which is right for the Jenkins template: its stages
    share one virtualenv.
    """
    text = path.read_text(encoding="utf-8")
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError:
        loaded = None
    if not isinstance(loaded, dict) or "jobs" not in loaded:
        return [(path.name, text)]
    out = []
    for name, job in (loaded.get("jobs") or {}).items():
        shell = [step.get("run", "") for step in (job or {}).get("steps", [])
                 if isinstance(step, dict)]
        out.append((f"{path.name}:{name}", "\n".join(shell)))
    return out


def _paths(shell: str) -> list[str]:
    """One entry per execution path, split on case-branch terminators."""
    return re.split(r"^\s*;;\s*$", shell, flags=re.MULTILINE)


def shipped() -> list[Path]:
    paths = sorted((ROOT / "templates").rglob("*"))
    paths += sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    return [p for p in paths if p.is_file()]


def _installs() -> list[tuple[str, str]]:
    """(environment, filename) for every requirements install that runs."""
    found = []
    for path in shipped():
        for name, shell in _blocks(path):
            for match in INSTALL.finditer(shell):
                if "--dry-run" in match.group("flags"):
                    continue
                found.append((name, match.group("file").strip("\"'")))
    return found


class TestTheScanReachesRealInstalls:
    """Every claim below is over a set this builds. An empty one proves it."""

    def test_definitions_were_found(self):
        assert len(shipped()) >= 4, (
            f"only {len(shipped())} shipped definition(s); this guard is about "
            f"the workflows and the templates and has found neither")

    def test_installs_were_found(self):
        found = _installs()
        assert len(found) >= 4, (
            f"only {len(found)} requirements install(s) found across the "
            f"workflows and templates; the matcher has stopped matching")


class TestOneResolutionPerEnvironment:

    def test_no_environment_installs_two_different_files(self):
        offences = []
        for path in shipped():
            for name, shell in _blocks(path):
                for branch in _paths(shell):
                    files = {m.group("file").strip("\"'")
                             for m in INSTALL.finditer(branch)
                             if "--dry-run" not in m.group("flags")}
                    if len(files) > 1:
                        offences.append(f"{name}: {', '.join(sorted(files))}")
        assert not offences, (
            "these install more than one requirements file into one "
            "environment, so the later resolution can move a pin the earlier "
            "one placed:\n  " + "\n  ".join(offences)
            + "\nAsk for them together instead: `pins --gate a --gate b`.")

    def test_no_installed_requirements_filename_varies(self):
        offences = [f"{name}: {file}" for name, file in _installs()
                    if "$" in file]
        assert not offences, (
            "these install a requirements file whose name is computed, which "
            "is one resolution per value however few lines it takes to "
            "write:\n  " + "\n  ".join(offences))
