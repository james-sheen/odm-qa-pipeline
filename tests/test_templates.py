"""The shipped templates, checked as artifacts rather than trusted as prose.

A composition template is the product here. Nobody runs this repository's own CI to
decide whether their pipeline is sound -- they copy these two files. So the files
themselves are what gets tested.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from odm_qa_pipeline.gates import names

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
