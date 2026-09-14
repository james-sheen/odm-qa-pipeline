"""The shipped templates, checked as artifacts rather than trusted as prose.

A composition template is the product here. Nobody runs this repository's own CI to
decide whether their pipeline is sound -- they copy these two files. So the files
themselves are what gets tested.
"""

from __future__ import annotations

import argparse
import importlib
import os
import re
import subprocess
from pathlib import Path

import pytest

from odm_qa_pipeline.gates import names

#: The CI switch that turns a missing validator into a red rather than a
#: skip. Imported rather than restated: it is a contract with
#: `.github/workflows/checks.yml`, and a second copy of it here would be a
#: second thing to change the day it moves.
from test_dmtf import REQUIRE

ROOT = Path(__file__).resolve().parent.parent
GITHUB = ROOT / "templates" / "github" / "odm-qa.yml"
JENKINS = ROOT / "templates" / "jenkins" / "Jenkinsfile"


@pytest.fixture(scope="module")
def workflow() -> dict:
    yaml = pytest.importorskip(
        "yaml", reason="pyyaml is not installed, so the template was never "
                       "parsed; install with '.[dev]'")
    return yaml.safe_load(GITHUB.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def steps(workflow) -> list[dict]:
    return workflow["jobs"]["qa"]["steps"]


class TestTheWorkflowIsAWorkflow:
    def test_it_parses(self, workflow):
        assert workflow["name"] == "odm-qa"

    def test_it_is_reusable(self, workflow):
        # PyYAML reads a bare `on:` key as the boolean True. Accept either, so
        # this test is about the template and not about the parser.
        triggers = workflow.get("on", workflow.get(True))
        assert "workflow_call" in triggers

    def test_it_takes_the_inputs_a_caller_needs(self, workflow):
        triggers = workflow.get("on", workflow.get(True))
        declared = set(triggers["workflow_call"]["inputs"])
        assert {"target", "config", "identity", "scenarios"} <= declared


class TestEveryGateRunsAndRecords:
    def test_all_four_gates_have_a_step(self, steps):
        text = " ".join(step.get("name", "") for step in steps).lower()
        for gate in names():
            assert gate in text, f"no step mentions the {gate} gate"

    def test_every_gate_records_a_result(self, steps):
        recorded = set()
        for step in steps:
            for match in re.finditer(r"--gate (\w+)", step.get("run", "")):
                recorded.add(match.group(1))
        assert set(names()) <= recorded, (
            f"these gates never call `record`, so a failure in them would leave "
            f"nothing for the aggregate step to read: "
            f"{sorted(set(names()) - recorded)}")

    def test_the_later_gates_run_even_after_an_earlier_one_fails(self, steps):
        """Otherwise a red gate 1 leaves gates 2-4 unreported, and the summary
        blames four things when one broke."""
        for step in steps:
            name = step.get("name", "")
            if name.startswith("Gate") and not name.startswith("Gate 1"):
                assert step.get("if") == "always()", (
                    f"{name!r} does not carry if: always()")

    def test_the_verdict_step_always_runs(self, steps):
        verdict = [s for s in steps if s.get("name") == "The verdict"]
        assert verdict, "no aggregation step"
        assert verdict[0].get("if") == "always()", (
            "the aggregate step is the one that reports gates which did not "
            "finish; skipping it on failure means it only ever runs when "
            "everything went well")

    def test_the_artifacts_are_kept_even_on_failure(self, steps):
        upload = [s for s in steps if "upload-artifact" in str(s.get("uses", ""))]
        assert upload and upload[0].get("if") == "always()"


class TestNoScriptInjection:
    """`${{ }}` is substituted before bash parses the line.

    A target URL containing a backtick or `$(...)` would execute. Inputs reach
    the shell through `env:` instead, which bash treats as data.
    """

    def test_no_expression_appears_inside_a_run_block(self, steps):
        offences = []
        for step in steps:
            for line in step.get("run", "").splitlines():
                if "${{" in line:
                    offences.append(f"{step.get('name')}: {line.strip()}")
        assert not offences, "; ".join(offences)

    def test_expressions_are_confined_to_env_and_with(self, workflow):
        """A line-level sweep, to catch what the parsed check above cannot.

        Comments are skipped, and the reason is the interesting half: the first
        run of this test failed on the comment that *documents* this rule. Prose
        about a rule is not a breach of it, and a text matcher cannot tell the
        difference -- which is precisely why the companion test works on the
        parsed `run:` blocks, where comments no longer exist.
        """
        raw = GITHUB.read_text(encoding="utf-8")
        for number, line in enumerate(raw.splitlines(), start=1):
            if "${{" not in line or line.lstrip().startswith("#"):
                continue
            assert re.match(r"\s*([A-Z_]+|python-version|name|path):", line), (
                f"line {number} interpolates an expression somewhere other than "
                f"an env: or with: assignment: {line.strip()}")


class TestTheJenkinsfileMatches:
    def test_it_exists_and_names_every_gate(self):
        text = JENKINS.read_text(encoding="utf-8")
        for gate in names():
            assert gate in text

    def test_it_aggregates_in_post_always(self):
        text = JENKINS.read_text(encoding="utf-8")
        post = text.split("post {", 1)[-1]
        assert "always" in post
        assert "odm-qa-pipeline aggregate" in post, (
            "the aggregate step must run in post/always for the same reason the "
            "GitHub one carries if: always()")

    def test_a_failing_gate_does_not_end_the_run(self):
        text = JENKINS.read_text(encoding="utf-8")
        assert text.count("catchError") >= len(names()), (
            "a gate whose non-zero exit aborts the build stops the later gates "
            "from reporting, and the verdict then comes from one stage rather "
            "than four")

    def test_the_build_still_fails_on_a_non_zero_verdict(self):
        text = JENKINS.read_text(encoding="utf-8")
        assert 'exit "${verdict}"' in text, (
            "catchError keeps the gates from failing the build, so the aggregate "
            "exit code has to be the thing that does; without this the pipeline "
            "is green whatever it found")


class TestTheGateOneVerdictSurvivesSetE:
    """`dmtf-verdict` exits `1` or `2` by design, and both templates capture it
    into a variable. Under `set -e` that assignment ends the step -- before the
    gate is recorded, which turns a gate that reported into a gate that vanished.
    So the capture stays inside the `set +e` region, and these pin both halves:
    the shell behaviour that makes it necessary, and the templates obeying it."""

    def test_a_nonzero_capture_under_set_e_really_does_end_the_script(self):
        """The premise, measured rather than remembered."""
        done = subprocess.run(
            ["bash", "-c", "set -e\ndetail=$(exit 2)\necho reached"],
            capture_output=True, text=True)
        assert done.returncode == 2
        assert "reached" not in done.stdout

    def test_the_same_capture_inside_set_plus_e_keeps_going(self):
        done = subprocess.run(
            ["bash", "-c", "set -e\nset +e\ndetail=$(exit 2)\ncode=$?\nset -e\n"
                           "echo reached ${code}"],
            capture_output=True, text=True)
        assert done.returncode == 0
        assert "reached 2" in done.stdout

    @pytest.mark.parametrize("path", [GITHUB, JENKINS],
                             ids=["github", "jenkins"])
    def test_the_capture_is_not_re_armed_before_it_runs(self, path):
        """Matched as statements, one line at a time.

        Written first as `text.index("set -e", ...)` and it failed on the
        template it was written for: the comment above the capture *explains*
        `set -e`, and a substring search counted the explanation as the
        statement. A word is not an instance.
        """
        lines = [line.strip() for line in
                 path.read_text(encoding="utf-8").splitlines()]
        relaxed = lines.index("set +e")
        capture = next(i for i, line in enumerate(lines)
                       if line.startswith("detail=$(odm-qa-pipeline dmtf-verdict"))
        rearmed = next(i for i, line in enumerate(lines)
                       if i > relaxed and line == "set -e")
        assert relaxed < capture < rearmed, (
            f"{path.name} re-arms set -e before capturing the gate 1 verdict; a "
            f"non-zero verdict would end the step and gate 1 would go unrecorded")


def commands(path: Path) -> list[str]:
    """The template's shell commands, with comments dropped and continuations
    joined.

    Both halves are load-bearing. The comment in each template that *explains*
    the two-walk defect spells out `detect --target`, so a text search over raw
    lines finds the defect in the prose describing its removal -- the same trap
    `TestNoScriptInjection` documents one class up. And the flags that matter
    here sit on continuation lines, so a line-at-a-time reader sees
    `cert-generator render` with no arguments at all.
    """
    joined, buffer = [], ""
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        buffer += " " + stripped[:-1] if stripped.endswith("\\") else " " + stripped
        if not stripped.endswith("\\"):
            joined.append(" ".join(buffer.split()))
            buffer = ""
    return [command for command in joined if command]


class TestOneCaptureJudgedTwice:
    """The property that was true of the GitHub workflow one release before it
    was true of the Jenkinsfile.

    Gate 2 used to run `detect --target` and then `coverage --target`, so the
    attestation and the coverage came from two different walks of the machine
    taken moments apart, and gate 4 combined them into one certificate without
    saying so. It was fixed in `templates/github/` and not in
    `templates/jenkins/`, and nothing here noticed: the class that claims to
    check the Jenkinsfile *matches* pins four structural properties and this was
    not among them.

    So every assertion below is parametrized over both files. A fix applied to
    one of two copies is a fix that is already drifting.
    """

    @pytest.mark.parametrize("path", [GITHUB, JENKINS],
                             ids=["github", "jenkins"])
    def test_the_machine_is_walked_exactly_once(self, path):
        captures = [c for c in commands(path)
                    if c.startswith("bmc-sensor-audit capture")]
        assert len(captures) == 1, (
            f"{path.name} runs `capture` {len(captures)} times; gate 2 is one "
            f"observation of the machine, judged more than once")

    @pytest.mark.parametrize("path", [GITHUB, JENKINS],
                             ids=["github", "jenkins"])
    def test_the_verdicts_read_the_file_not_the_machine(self, path):
        for command in commands(path):
            if not re.match(r"bmc-sensor-audit (detect|coverage)\b", command):
                continue
            assert "--walk" in command, (
                f"{path.name}: {command.split()[1]} does not read the captured "
                f"walk")
            assert "--target" not in command, (
                f"{path.name}: {command.split()[1]} walks the machine again "
                f"instead of judging the capture gate 2 already took")

    @pytest.mark.parametrize("path", [GITHUB, JENKINS],
                             ids=["github", "jenkins"])
    def test_the_capture_is_checked_for_completeness(self, path):
        checks = [c for c in commands(path)
                  if c.startswith("bmc-sensor-audit validate-walk")]
        assert checks, (
            f"{path.name} never runs `validate-walk`; `capture` exits 2 both "
            f"when it could not reach the machine and when it reached it and "
            f"wrote a partial walk on purpose, so the exit code alone cannot "
            f"say whether this gate got a whole one")
        assert all("--require-complete" in c for c in checks), (
            f"{path.name} validates the walk without --require-complete, which "
            f"accepts the partial walk this gate cannot judge")

    @pytest.mark.parametrize("path", [GITHUB, JENKINS],
                             ids=["github", "jenkins"])
    def test_the_certificate_names_the_capture_it_was_judged_from(self, path):
        renders = [c for c in commands(path)
                   if c.startswith("cert-generator render")]
        assert renders, f"{path.name} has no certificate render"
        for command in renders:
            assert "--walk" in command, (
                f"{path.name}: the certificate does not name the walk both "
                f"verdicts came from, so nothing ties the document to the "
                f"evidence and a recipient has no handle to match")

    def test_the_two_templates_agree_on_all_of_it(self):
        """The pairwise form of the four above.

        Written because each of those could be satisfied by both files drifting
        in the same direction. This one fails if the referee is invoked with a
        different shape in one template than the other, whatever that shape is.
        """
        def shape(path):
            return [re.sub(r'"[^"]*"', '"X"', c) for c in commands(path)
                    if c.startswith(("bmc-sensor-audit ", "cert-generator "))]
        assert shape(GITHUB) == shape(JENKINS), (
            "the templates invoke the tools differently; whichever is right, "
            "one of them is shipping the other's bug")


VALIDATORS = {"rf_service_validator": "redfish_service_validator",
              "rf_protocol_validator": "redfish_protocol_validator"}


def _captured_parser(module):
    """The tool's own parser, taken before it can act on anything.

    Both validators build theirs inside `main()`, so there is nothing to import.
    """
    captured = {}
    original = argparse.ArgumentParser.parse_args

    def spy(self, *args, **kwargs):
        captured["parser"] = self
        raise SystemExit(0)

    argparse.ArgumentParser.parse_args = spy
    try:
        module.main()
    except SystemExit:
        pass
    finally:
        argparse.ArgumentParser.parse_args = original
    assert "parser" in captured, (
        f"{module.__name__} no longer builds its parser through parse_args, so "
        f"this check has stopped asking the tool anything")
    return captured["parser"]


@pytest.fixture(scope="module")
def parsers():
    """Each validator's parser, or an honest reason there is none.

    Module scope and module level, deliberately: a class-scoped fixture written
    as an instance method is deprecated in pytest 9, and a fixture whose
    declaration form quietly stops working is exactly F1.
    """
    required = os.environ.get(REQUIRE) == "1"
    found = {}
    for command, package in VALIDATORS.items():
        try:
            module = importlib.import_module(f"{package}.console_scripts")
        except ImportError as error:                       # pragma: no cover
            if required:
                pytest.fail(f"{REQUIRE}=1 and {package} is not installed, so "
                            f"the only oracle for gate 1's flags could not "
                            f"run: {error}")
            pytest.skip(f"{package} is not installed here; the templates have "
                        f"no oracle in this environment")
        found[command] = _captured_parser(module)
    return found


class TestEveryFlagIsOneTheToolActuallyHas:
    """The class `--nochkcert` belonged to, and that nothing here could see.

    Both templates sent `rf_service_validator --nochkcert` from the first
    release until 2026-09-14. No release of DMTF's service validator has that
    flag -- not 3.1.0, 3.1.3, 3.1.5 or 3.1.7, which is the whole range
    `pins.json` admits, and not 2.4 or 2.5 either -- so argparse answered
    `unrecognized arguments`, the step exited 2 before reaching the BMC, and
    gate 1's service half never ran in any pipeline that copied either file.

    `TestTheTwoTemplatesAgree` could not catch it and never will: both files
    carried the same impossible flag, so they agreed. Two copies of one string
    matching says nothing about whether the string is right, and every check
    above this one compares the templates to each other or to this repository's
    own idea of them.

    So this one asks the tool. The parser is built inside `main()` in both
    validators, which means there is nothing to import -- spying on `parse_args`
    is how you get the published tool to state what it accepts without asking it
    to do anything. A list of valid flags maintained here would be a third copy,
    written from the same reading that produced the bug.

    Long flags only. The short ones (`-u`, `-p`, `-r`) are single letters that
    collide across tools by design, and `parse_known_args` cannot tell a missing
    value from an unknown letter.
    """

    @pytest.mark.parametrize("path", [GITHUB, JENKINS],
                             ids=["github", "jenkins"])
    def test_the_validators_are_sent_only_flags_they_declare(self, parsers, path):
        checked = 0
        for command in commands(path):
            parser = parsers.get(command.split()[0])
            if parser is None:
                continue
            for flag in re.findall(r"(?<!\S)--[a-z][a-z0-9-]*", command):
                # A value is supplied because a flag that takes one would
                # otherwise consume the end of the list; an unknown flag comes
                # back in `unknown` either way, and that is the whole question.
                _, unknown = parser.parse_known_args([flag, "unused"])
                assert flag not in unknown, (
                    f"{path.name} sends {flag} to {command.split()[0]}, which "
                    f"does not declare it. argparse will exit 2 on a usage "
                    f"error before the machine is contacted, and gate 1 will "
                    f"report incomplete for a reason that is not the machine")
                checked += 1
        assert checked, (
            f"{path.name}: no validator invocation was found, so this check "
            f"passed without reading anything")
