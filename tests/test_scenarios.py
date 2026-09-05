"""Finding another repository's scenarios without naming any of its paths.

The three canaries that use this named `scenarios/stuck-at.yaml` and `scenarios/`
in workflow YAML. Those are paths into a repository this one does not control, and
the orchestrator's 0.3 rewrite moves them. A path written into three workflows is
three things to update on the day it moves, and nothing type-checks any of them.

What is asserted here is the replacement contract: a scenario is whatever declares
itself one, the runnable set is whatever the installed build can name, and a
checkout offering nothing runnable is a **broken seam**, not a clean run.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from odm_qa_pipeline.scenarios import (EXIT_CLEAN, EXIT_INCOMPLETE,
                                       EXIT_REGRESSION, ScenarioError,
                                       discover, exercise)

SCENARIO = "format: qa-scenario/2\nname: a thing\n"


def _fake(check: dict[str, int] | None = None, run: dict[str, int] | None = None,
          default_check: int = 0, default_run: int = 0):
    """A runner that answers by file name, so a test can say what each did."""
    calls: list[list[str]] = []

    def runner(argv):
        calls.append(list(argv))
        name = Path(argv[-1]).name
        code = ((check or {}).get(name, default_check) if argv[-2] == "check"
                else (run or {}).get(name, default_run))
        return subprocess.CompletedProcess(argv, code, stdout="", stderr="said why")

    runner.calls = calls
    return runner


@pytest.fixture
def checkout(tmp_path):
    (tmp_path / "anywhere" / "at" / "all").mkdir(parents=True)
    (tmp_path / "anywhere" / "at" / "all" / "one.yaml").write_text(SCENARIO)
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "two.yml").write_text(SCENARIO)
    return tmp_path


class TestDiscovery:
    def test_it_finds_by_the_marker_wherever_the_file_sits(self, checkout):
        """Two scenarios, two directories, neither named by this code."""
        assert [p.name for p in discover(checkout)] == ["one.yaml", "two.yml"]

    def test_a_yaml_that_is_not_a_scenario_is_not_one(self, checkout):
        (checkout / "config.yaml").write_text("name: not a scenario\n")
        assert "config.yaml" not in [p.name for p in discover(checkout)]

    def test_prose_mentioning_the_format_is_not_a_scenario(self, checkout):
        """The marker is matched at the start of a line.

        A README saying *the format: qa-scenario/2 is versioned* counts as a
        scenario under a substring test, and the canary then runs a document."""
        (checkout / "notes.yaml").write_text(
            "# we write format: qa-scenario/2 at the top of each file\n")
        assert "notes.yaml" not in [p.name for p in discover(checkout)]

    def test_a_missing_directory_is_refused_not_reported_empty(self, tmp_path):
        with pytest.raises(ScenarioError, match="not a directory"):
            discover(tmp_path / "nope")


class TestScope:
    def test_what_check_refuses_is_out_of_scope_not_a_failure(self, checkout):
        """A scenario for a vertical whose plugin is absent is not this seam."""
        report = exercise(checkout, run=_fake(check={"two.yml": 2}))
        assert [p.name for p in report.in_scope] == ["one.yaml"]
        assert [p.name for p in report.out_of_scope] == ["two.yml"]
        assert report.exit_code == EXIT_CLEAN

    def test_only_in_scope_scenarios_are_run(self, checkout):
        runner = _fake(check={"two.yml": 2})
        exercise(checkout, run=runner)
        ran = [Path(c[-1]).name for c in runner.calls if c[-2] == "run"]
        assert ran == ["one.yaml"]


class TestTheVerdict:
    def test_all_clean_is_clean(self, checkout):
        assert exercise(checkout, run=_fake()).exit_code == EXIT_CLEAN

    def test_a_wrong_verdict_is_a_regression(self, checkout):
        report = exercise(checkout, run=_fake(run={"two.yml": 1}))
        assert report.exit_code == EXIT_REGRESSION

    def test_could_not_complete_outranks_a_wrong_verdict(self, checkout):
        """Both present: `2` must win, because it says the seam did not answer."""
        report = exercise(checkout, run=_fake(run={"one.yaml": 1, "two.yml": 2}))
        assert report.exit_code == EXIT_INCOMPLETE

    def test_nothing_in_scope_is_incomplete_not_clean(self, checkout):
        """The whole point. An empty set passes every assertion made about it."""
        report = exercise(checkout, run=_fake(default_check=2))
        assert report.in_scope == ()
        assert report.exit_code == EXIT_INCOMPLETE
        assert "not the same as a clean one" in report.render()

    def test_a_checkout_with_no_scenarios_at_all_is_incomplete(self, tmp_path):
        report = exercise(tmp_path, run=_fake())
        assert report.found == ()
        assert report.exit_code == EXIT_INCOMPLETE


class TestTheToolItself:
    def test_a_missing_tool_says_so_and_does_not_traceback(self, checkout):
        with pytest.raises(ScenarioError, match="not on PATH"):
            exercise(checkout, tool="definitely-not-a-program-8f3a")

    def test_a_command_may_have_arguments(self, checkout):
        """`python3 -m qa_orchestrator.cli` is how a build that is not installed
        gets exercised at all; a single-word tool cannot reach one."""
        runner = _fake()
        exercise(checkout, tool="python3 -m qa_orchestrator.cli", run=runner)
        assert runner.calls[0][:3] == ["python3", "-m", "qa_orchestrator.cli"]

    def test_an_empty_command_is_refused(self, checkout):
        with pytest.raises(ScenarioError, match="no orchestrator command"):
            exercise(checkout, tool="   ", run=_fake())


class TestTheReport:
    def test_it_names_every_scenario_it_ran(self, checkout):
        rendered = exercise(checkout, run=_fake()).render()
        assert "one.yaml" in rendered and "two.yml" in rendered

    def test_a_failure_carries_what_the_tool_said(self, checkout):
        rendered = exercise(checkout, run=_fake(run={"one.yaml": 2})).render()
        assert "said why" in rendered


class TestABrokenToolIsNotAnOutOfScopeScenario:
    """A tool that cannot run answers nothing, and must not be filed as a
    scenario this build merely could not name. Measured: the orchestrator exits
    `2` when it refuses and `1` when it cannot start, so the two are separable."""

    def test_an_undocumented_exit_is_refused_by_name(self, checkout):
        with pytest.raises(ScenarioError, match="outside its documented"):
            exercise(checkout, run=_fake(default_check=1))

    def test_the_refusal_says_which_scenario_it_was_on(self, checkout):
        with pytest.raises(ScenarioError, match="one.yaml"):
            exercise(checkout, run=_fake(default_check=127))

    def test_a_documented_refusal_is_still_only_out_of_scope(self, checkout):
        report = exercise(checkout, run=_fake(default_check=2))
        assert report.out_of_scope and report.exit_code == EXIT_INCOMPLETE
