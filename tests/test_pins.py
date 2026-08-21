"""One home for every version constraint, and a check that it stayed the only one.

A range written into the manifest *and* into a workflow is two copies of one fact.
They agree on the day they are written and there is no check that would notice when
they stop -- the workflow keeps running, the manifest keeps looking authoritative,
and the pipeline resolves something nobody chose.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from odm_qa_pipeline import pins
from odm_qa_pipeline.gates import names

ROOT = Path(__file__).resolve().parent.parent

# `name>=1.2`, `name==1.2`, `name[extra]<2` -- a requirement specifier, as opposed
# to `python-version: "3.12"` or `actions/checkout@v4`, which are pins of a
# different kind and belong exactly where they are.
#
# **It took two goes to write, and both failures were the same mistake.** A first
# pattern allowed whitespace before the operator and flagged `assert version == 1`
# inside a canary's Python heredoc. A second spelled the operator `[><=!]=?`,
# which also matches a bare `=`, so every `code=1` in a shell block tripped it.
# Neither was a requirement; both were a matcher too loose for the thing it was
# looking for.
#
# That matters beyond tidiness: a guard with false positives is a guard the next
# person loosens, and a loosened guard stops catching the real thing. So the
# operator set is spelled out, no whitespace is allowed before it, and PIP_LINE
# below covers the spaced form pip also accepts -- nothing is given up by being
# strict here.
SPECIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.\-]*(?:\[[A-Za-z0-9,_\-]+\])?"
                       r"(?:[><]=?|[=!]=)\d")

# The other half: anything handed to `pip install` that carries a version number.
# Catches `pip install foo >= 1.2` and `pip install foo==1.2` alike, whatever the
# spacing, because that line is the actual risk surface.
PIP_LINE = re.compile(r"pip\s+install\b.*?\d+\.\d")


def shipped_definitions() -> list[Path]:
    paths = sorted((ROOT / "templates").rglob("*"))
    paths += sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    return [p for p in paths if p.is_file()]


class TestTheManifest:
    def test_it_loads(self):
        assert pins.load()["components"]

    def test_every_component_carries_a_requirement(self):
        for name, entry in pins.load()["components"].items():
            assert entry["requirement"], name

    def test_every_component_names_a_gate_that_exists(self):
        for name, entry in pins.load()["components"].items():
            assert entry.get("gate") in names(), (
                f"{name} is assigned to gate {entry.get('gate')!r}, which this "
                f"pipeline does not run")

    def test_every_gate_has_something_supplying_it(self):
        assigned = {e.get("gate") for e in pins.load()["components"].values()}
        for gate in names():
            assert gate in assigned, (
                f"gate {gate!r} has no component in the manifest, so "
                f"`pins --gate {gate}` would install nothing and the gate would "
                f"fail with command-not-found rather than a useful message")

    def test_it_travels_with_the_package(self):
        """Not at the repository root. There it resolves through `../../`, which
        is correct from a checkout and points outside site-packages once
        installed -- so the manifest would be missing for everyone who installed
        the tool rather than cloned it."""
        assert pins.PINS_PATH.parent.name == "odm_qa_pipeline"
        assert pins.PINS_PATH.exists()


class TestAnUnpinnedComponentMustSayWhatItCosts:
    def test_the_unpublished_ones_explain_themselves(self):
        for name, why in pins.unpinned().items():
            assert len(why) > 40, f"{name} has a token reason, not an explanation"
            assert "pin" in why.lower() or "branch" in why.lower()

    def test_a_missing_reason_is_refused(self, tmp_path):
        bad = tmp_path / "pins.json"
        bad.write_text('{"components": {"x": {"requirement": "x", '
                       '"published": false}}}')
        with pytest.raises(pins.PinsError) as raised:
            pins.load(bad)
        assert "why_unpinned" in str(raised.value)

    def test_the_two_unreleased_repositories_are_the_ones_flagged(self):
        """Named rather than counted. If one of them ships and the manifest is
        not updated, this goes red and says which."""
        assert set(pins.unpinned()) == {"qa-orchestrator", "cert-generator"}


class TestNoDefinitionRepeatsAConstraint:
    def test_the_matchers_can_actually_match(self):
        """The guard below asserts an absence. Absence checks pass when the
        matcher is broken, so prove both match known-bad lines first."""
        assert SPECIFIER.search("pip install bmc-sensor-audit>=0.1.0,<0.2")
        assert SPECIFIER.search("redfish-service-validator==3.1.6")
        assert SPECIFIER.search("pip install 'bmc-sensor-audit[detect]>=0.1.0'")
        assert PIP_LINE.search("python3 -m pip install foo >= 1.2")

    def test_the_matchers_leave_legitimate_lines_alone(self):
        for benign in ('      python-version: "3.12"',
                       "      - uses: actions/checkout@v4",
                       "worst=$(( a > b ? a : b ))",
                       "assert version == 1, f'the engine now speaks {version}'",
                       "python3 -m pip install --quiet -e '.[dev]'",
                       "python3 -m pip install --quiet $(odm-qa-pipeline pins --gate dmtf)",
                       "            code=1; detail=\"non-conformance\"",
                       "          icode=2; detail=\"a scenario would not parse\"",
                       '            test "${code}" -eq 1 || exit 1'):
            assert not SPECIFIER.search(benign), benign
            assert not PIP_LINE.search(benign), benign

    def test_there_is_something_to_check(self):
        assert shipped_definitions(), "no templates or workflows were found"

    @pytest.mark.parametrize("path", shipped_definitions(),
                             ids=lambda p: p.name)
    def test_no_requirement_specifier_appears(self, path):
        offences = []
        for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1):
            if SPECIFIER.search(line) or PIP_LINE.search(line):
                offences.append(f"line {number}: {line.strip()}")
        assert not offences, (
            f"{path.relative_to(ROOT)} spells out a version constraint; ask "
            f"`odm-qa-pipeline pins` instead so there is one home for it: "
            + "; ".join(offences))


class TestPinsOutputIsConsumedAsARequirementsFile:
    """A requirement can contain spaces, so it cannot be word-split.

    `qa-orchestrator @ git+https://...` is the PEP 508 direct-reference form and
    it has two spaces in it. Fed to pip as `$(odm-qa-pipeline pins --gate
    injection)` the shell splits it into three arguments and pip stops on the bare
    `@` -- *Invalid requirement: '@'*.

    Every shipped definition therefore writes the output to a file and installs
    with `-r`, which is the only form that survives whitespace. CI found this;
    nothing in the suite did, because every test consumed the manifest through
    Python and never through a shell.
    """

    def test_a_requirement_with_whitespace_actually_exists(self):
        """Non-vacuity. If every requirement became a bare name the rule below
        would still pass while protecting nothing, so pin the premise."""
        spaced = [name for name, entry in pins.load()["components"].items()
                  if " " in entry["requirement"]]
        assert spaced, ("no requirement contains whitespace any more; if that is "
                        "deliberate, this rule and its guard can go")

    @pytest.mark.parametrize("path", shipped_definitions(),
                             ids=lambda p: p.name)
    def test_no_definition_word_splits_the_manifest(self, path):
        offences = []
        for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.lstrip().startswith(("#", "//")):
                continue
            if "pip install" in line and "$(odm-qa-pipeline pins" in line:
                offences.append(f"line {number}: {line.strip()}")
        assert not offences, (
            f"{path.relative_to(ROOT)} word-splits the manifest into pip; write "
            f"it to a file and install with -r, because a direct reference "
            f"contains spaces: " + "; ".join(offences))

    def test_every_gate_produces_something_pip_could_read(self):
        """One requirement per line, nothing else -- no headers, no blanks."""
        for gate in names():
            lines = pins.requirements_for(gate)
            assert lines, gate
            for line in lines:
                assert line.strip() == line
                assert "\n" not in line


class TestLookups:
    def test_one_component(self):
        assert pins.requirement("bmc-sensor-audit").startswith("bmc-sensor-audit")

    def test_an_unknown_component_is_refused(self):
        with pytest.raises(pins.PinsError):
            pins.requirement("no-such-tool")

    def test_a_gate_returns_everything_it_needs(self):
        assert len(pins.requirements_for("dmtf")) == 2

    def test_an_unknown_gate_returns_nothing_rather_than_raising(self):
        assert pins.requirements_for("no-such-gate") == []
