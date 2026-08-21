"""The aggregation rules, and the one nothing else in the suite can enforce."""

from __future__ import annotations

import json

import pytest

from odm_qa_pipeline import RESULT_FORMAT
from odm_qa_pipeline.aggregate import (CLEAN, INCOMPLETE, REGRESSIONS, VERDICTS,
                                       AggregateError, GateResult, aggregate,
                                       parse_assignment, read_results, render)
from odm_qa_pipeline.gates import names

ALL = list(names())


def results(**codes) -> list[GateResult]:
    return [GateResult(gate=name, exit_code=code) for name, code in codes.items()]


def full(**overrides) -> list[GateResult]:
    codes = {name: CLEAN for name in ALL}
    codes.update(overrides)
    return results(**codes)


class TestPrecedence:
    def test_all_clean_is_clean(self):
        assert aggregate(full())["exit_code"] == CLEAN

    def test_one_regression_carries(self):
        assert aggregate(full(coverage=REGRESSIONS))["exit_code"] == REGRESSIONS

    def test_one_incomplete_carries(self):
        assert aggregate(full(dmtf=INCOMPLETE))["exit_code"] == INCOMPLETE

    def test_could_not_complete_beats_a_regression(self):
        """The rule this suite is built around. A run that found a regression AND
        failed to finish reports 2: 1 would let a reader conclude the rest was
        checked."""
        summary = aggregate(full(coverage=REGRESSIONS, injection=INCOMPLETE))
        assert summary["exit_code"] == INCOMPLETE
        assert summary["verdict"] == "incomplete"

    def test_the_deciding_gate_is_named(self):
        summary = aggregate(full(injection=INCOMPLETE))
        assert summary["decided_by"] == ["injection"]

    def test_nothing_is_named_when_clean(self):
        assert aggregate(full())["decided_by"] == []


class TestAGateThatDidNotRunHasNotPassed:
    def test_a_missing_gate_is_incomplete(self):
        summary = aggregate(results(dmtf=CLEAN, coverage=CLEAN))
        assert summary["exit_code"] == INCOMPLETE
        assert set(summary["missing"]) == {"injection", "certificate"}

    def test_every_other_gate_being_clean_does_not_rescue_it(self):
        """The failure this module exists for: a pipeline where one step was
        commented out weeks ago and every run since came back green."""
        summary = aggregate(full(injection=CLEAN)[:3])
        assert summary["exit_code"] == INCOMPLETE

    def test_no_results_at_all_is_incomplete_not_clean(self):
        summary = aggregate([])
        assert summary["exit_code"] == INCOMPLETE
        assert summary["missing"] == ALL

    def test_the_row_says_why(self):
        summary = aggregate(results(dmtf=CLEAN), expected=["dmtf", "coverage"])
        row = [r for r in summary["gates"] if r["gate"] == "coverage"][0]
        assert "did not run has not passed" in row["detail"]


class TestOptionalIsADecisionOnTheRecord:
    def test_an_optional_gate_may_be_absent(self):
        summary = aggregate(full()[:3], optional=["certificate"])
        assert summary["exit_code"] == CLEAN
        assert summary["skipped"] == ["certificate"]

    def test_it_is_still_listed(self):
        summary = aggregate(full()[:3], optional=["certificate"])
        row = [r for r in summary["gates"] if r["gate"] == "certificate"][0]
        assert "declared optional" in row["verdict"]

    def test_an_optional_gate_that_did_run_is_still_judged(self):
        """Optional means may-be-absent, not may-fail-quietly."""
        summary = aggregate(full(certificate=REGRESSIONS),
                            optional=["certificate"])
        assert summary["exit_code"] == REGRESSIONS


class TestAnExitCodeNobodyDefined:
    def test_command_not_found_reads_as_incomplete(self):
        result = GateResult(gate="dmtf", exit_code=127)
        assert result.exit_code == INCOMPLETE
        assert result.raw_exit_code == 127

    def test_the_raw_code_survives_into_the_summary(self):
        summary = aggregate(full(dmtf=127))
        row = [r for r in summary["gates"] if r["gate"] == "dmtf"][0]
        assert row["raw_exit_code"] == 127
        assert "exited 127" in row["detail"]

    def test_it_does_not_leak_into_the_verdict(self):
        assert aggregate(full(dmtf=127))["exit_code"] == INCOMPLETE

    def test_a_negative_code_is_also_incomplete(self):
        assert GateResult(gate="dmtf", exit_code=-9).exit_code == INCOMPLETE

    def test_a_non_integer_is_refused(self):
        with pytest.raises(AggregateError):
            GateResult(gate="dmtf", exit_code="0")

    def test_a_boolean_is_refused(self):
        """`True` is an int in Python and would silently mean 1."""
        with pytest.raises(AggregateError):
            GateResult(gate="dmtf", exit_code=True)


class TestThingsThatMakeASummaryMeaningless:
    def test_two_results_for_one_gate_is_refused(self):
        with pytest.raises(AggregateError) as raised:
            aggregate([GateResult("dmtf", 0), GateResult("dmtf", 1)])
        assert "which run" in str(raised.value)

    def test_a_gate_this_pipeline_does_not_declare_is_refused(self):
        with pytest.raises(AggregateError) as raised:
            aggregate([GateResult("burn-in", 0)])
        assert "burn-in" in str(raised.value)


class TestReadingResultsFromDisk:
    def _write(self, directory, gate, code, fmt=RESULT_FORMAT):
        (directory / f"{gate}.json").write_text(json.dumps(
            {"format": fmt, "gate": gate, "exit_code": code}))

    def test_a_directory_round_trips(self, tmp_path):
        for gate in ALL:
            self._write(tmp_path, gate, 0)
        assert aggregate(read_results(tmp_path))["exit_code"] == CLEAN

    def test_a_wrong_format_is_refused(self, tmp_path):
        self._write(tmp_path, "dmtf", 0, fmt="something/else/1")
        with pytest.raises(AggregateError) as raised:
            read_results(tmp_path)
        assert "format" in str(raised.value)

    def test_broken_json_is_refused(self, tmp_path):
        (tmp_path / "dmtf.json").write_text("{not json")
        with pytest.raises(AggregateError):
            read_results(tmp_path)

    def test_a_missing_directory_is_refused(self, tmp_path):
        with pytest.raises(AggregateError):
            read_results(tmp_path / "absent")


class TestShellAssignments:
    def test_name_and_code(self):
        result = parse_assignment("coverage=1")
        assert (result.gate, result.exit_code) == ("coverage", REGRESSIONS)

    def test_name_code_and_detail(self):
        result = parse_assignment("coverage=1:two sensors absent")
        assert result.detail == "two sensors absent"

    def test_a_malformed_assignment_is_refused(self):
        with pytest.raises(AggregateError):
            parse_assignment("coverage")

    def test_a_non_numeric_code_is_refused(self):
        with pytest.raises(AggregateError):
            parse_assignment("coverage=clean")


class TestTheRenderedSummary:
    def test_it_names_the_missing_gate(self):
        text = render(aggregate(results(dmtf=CLEAN)))
        assert "gates that never reported" in text
        assert "injection" in text

    def test_it_leads_with_the_verdict(self):
        assert render(aggregate(full())).startswith("pipeline: clean (exit 0)")

    def test_one_vocabulary_for_the_three_numbers(self):
        assert VERDICTS == {0: "clean", 1: "regressions", 2: "incomplete"}
