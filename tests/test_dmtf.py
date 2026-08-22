"""Gate 1, scored from what the validators wrote.

The case that matters is the first one below, and it is the reason this file
exists: a service validator that cannot reach the BMC exits `1` and has already
written its debug log into the directory. The rule this replaces looked for any
file, found the log, and recorded a regression against the machine. That is a `2`
reported as a `1` -- a claim that conformance was measured and failed, when
nothing was measured at all -- in the one gate this suite borrows rather than
builds.

The last class is the part worth the most: it does not use a fixture written from
reading the source. It asks the published validator to write its own results file
and checks this reader against that. A fixture I write from the same understanding
that produced the parser can only ever confirm I was consistent.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

import pytest

from odm_qa_pipeline import dmtf
from odm_qa_pipeline.cli import main

REQUIRE = "ODM_QA_REQUIRE_DMTF"


def _service_log(logdir, name="RedfishServiceValidatorDebug_01_01_2026_000000.log"):
    """What the tool writes before it contacts anything -- console_scripts.py:141."""
    run = logdir / "2026-01-01-000000"
    run.mkdir(parents=True, exist_ok=True)
    (run / name).write_text("Redfish Service Validator, Version 3.1.6\n")
    return run


def _service_report(logdir):
    run = _service_log(logdir)
    report = run / "RedfishServiceValidatorReport_01_01_2026_000000.html"
    report.write_text("<html><body>a report</body></html>")
    return report


def _protocol_results(logdir, *, passed=40, failed=0, suite="Protocol Validations"):
    logdir.mkdir(parents=True, exist_ok=True)
    (logdir / "results.json").write_text(json.dumps({
        "ToolName": "Redfish-Protocol-Validator v1.3.1",
        "TestResults": {
            suite: {"pass": passed, "fail": failed, "skip": 0, "warn": 0},
            "ErrorMessages": [],
        },
    }))


class TestTheHeuristicThisReplaces:

    def test_a_log_without_a_report_is_incomplete_not_a_regression(self, tmp_path):
        """The whole point. The old rule scored this `1`."""
        _service_log(tmp_path)
        _protocol_results(tmp_path)
        verdict = dmtf.read(tmp_path, service_exit=1, protocol_exit=0)
        assert verdict.exit_code == dmtf.INCOMPLETE
        assert "did not reach a verdict" in verdict.detail

    def test_a_log_is_named_as_not_being_a_verdict(self, tmp_path):
        _service_log(tmp_path)
        _protocol_results(tmp_path)
        assert "debug log" in dmtf.read(tmp_path, 1, 0).detail

    def test_a_report_with_a_failing_exit_is_a_regression(self, tmp_path):
        _service_report(tmp_path)
        _protocol_results(tmp_path)
        verdict = dmtf.read(tmp_path, service_exit=1, protocol_exit=0)
        assert verdict.exit_code == dmtf.REGRESSION
        assert "non-conformance" in verdict.detail

    def test_a_report_with_a_clean_exit_is_clean(self, tmp_path):
        _service_report(tmp_path)
        _protocol_results(tmp_path)
        assert dmtf.read(tmp_path, 0, 0).exit_code == dmtf.CLEAN


class TestForeignExits:
    """Only 0 and 1 are values these tools return, so nothing else is a verdict."""

    @pytest.mark.parametrize("code", [2, 127, 130, -1])
    def test_a_foreign_service_exit_is_incomplete(self, tmp_path, code):
        _service_report(tmp_path)
        _protocol_results(tmp_path)
        verdict = dmtf.read(tmp_path, service_exit=code, protocol_exit=0)
        assert verdict.exit_code == dmtf.INCOMPLETE
        assert str(code) in verdict.detail, "the raw code is the useful half"

    def test_a_foreign_protocol_exit_is_incomplete(self, tmp_path):
        _service_report(tmp_path)
        _protocol_results(tmp_path)
        assert dmtf.read(tmp_path, 0, 127).exit_code == dmtf.INCOMPLETE


class TestTheProtocolHalfIsRead:

    def test_failures_are_counted_out_of_the_file(self, tmp_path):
        _service_report(tmp_path)
        _protocol_results(tmp_path, passed=38, failed=2)
        verdict = dmtf.read(tmp_path, 0, 1)
        assert verdict.exit_code == dmtf.REGRESSION
        assert "2 failure(s) over 40 check(s)" in verdict.detail

    def test_a_clean_run_reports_its_denominator(self, tmp_path):
        _service_report(tmp_path)
        _protocol_results(tmp_path, passed=41)
        assert "over 41 check(s)" in dmtf.read(tmp_path, 0, 0).detail

    def test_several_suites_are_summed(self, tmp_path):
        _service_report(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "results.json").write_text(json.dumps({
            "TestResults": {"A": {"pass": 1, "fail": 1},
                            "B": {"pass": 2, "fail": 0},
                            "ErrorMessages": []}}))
        assert "1 failure(s) over 4 check(s)" in dmtf.read(tmp_path, 0, 1).detail

    def test_no_results_file_is_incomplete(self, tmp_path):
        _service_report(tmp_path)
        verdict = dmtf.read(tmp_path, 0, 1)
        assert verdict.exit_code == dmtf.INCOMPLETE
        assert "results.json" in verdict.detail

    def test_an_unrecognised_shape_claims_nothing(self, tmp_path):
        _service_report(tmp_path)
        (tmp_path / "results.json").write_text(json.dumps({"Totals": {"bad": 1}}))
        verdict = dmtf.read(tmp_path, 0, 1)
        assert verdict.exit_code == dmtf.INCOMPLETE
        assert "no longer describes the tool" in verdict.detail

    def test_unparseable_json_claims_nothing(self, tmp_path):
        _service_report(tmp_path)
        (tmp_path / "results.json").write_text("{not json")
        assert dmtf.read(tmp_path, 0, 1).exit_code == dmtf.INCOMPLETE

    def test_an_exit_disagreeing_with_the_counts_is_reported_not_resolved(
            self, tmp_path):
        """`sys.exit(int(fail > 0))` is the tie. If it breaks, the version moved."""
        _service_report(tmp_path)
        _protocol_results(tmp_path, passed=40, failed=0)
        verdict = dmtf.read(tmp_path, 0, 1)
        assert verdict.exit_code == dmtf.INCOMPLETE
        assert "out of date" in verdict.detail


class TestHalfAnAnswer:

    def test_a_validator_that_was_not_run_is_incomplete(self, tmp_path):
        _service_report(tmp_path)
        _protocol_results(tmp_path)
        assert dmtf.read(tmp_path, 0, None).exit_code == dmtf.INCOMPLETE
        assert dmtf.read(tmp_path, None, 0).exit_code == dmtf.INCOMPLETE

    def test_a_missing_directory_is_incomplete(self, tmp_path):
        assert dmtf.read(tmp_path / "nowhere", 0, 0).exit_code == dmtf.INCOMPLETE

    def test_precedence_is_max(self, tmp_path):
        """A regression and a could-not-complete together report the latter."""
        _service_log(tmp_path)
        _protocol_results(tmp_path, passed=38, failed=2)
        assert dmtf.read(tmp_path, 1, 1).exit_code == dmtf.INCOMPLETE


class TestTheCommand:

    def test_it_exits_with_the_gate_code_and_prints_the_detail(self, tmp_path,
                                                               capsys):
        _service_log(tmp_path)
        _protocol_results(tmp_path)
        code = main(["dmtf-verdict", "--logdir", str(tmp_path),
                     "--service-exit", "1", "--protocol-exit", "0"])
        assert code == dmtf.INCOMPLETE
        assert "did not reach a verdict" in capsys.readouterr().out

    def test_omitting_an_exit_code_is_allowed_and_says_what_it_means(self,
                                                                    tmp_path,
                                                                    capsys):
        _service_report(tmp_path)
        _protocol_results(tmp_path)
        assert main(["dmtf-verdict", "--logdir", str(tmp_path),
                     "--service-exit", "0"]) == dmtf.INCOMPLETE
        assert "was not run" in capsys.readouterr().out


class TestThePublisherIsTheOracle:
    """The parser was written by reading the validator. A fixture written the same
    way could only prove I was consistent with myself, so this asks the installed
    tool to write the file and checks the reader against that."""

    def _sut(self, failed):
        from redfish_protocol_validator.constants import Result

        counts = {Result.PASS: 40 - failed, Result.FAIL: failed,
                  Result.WARN: 0, Result.NOT_TESTED: 0}

        class Stub:
            rhost = "https://bmc.invalid"
            manufacturer = product = model = firmware_version = "x"

            def summary_count(self, result):
                return counts[result]

        return Stub()

    @pytest.fixture
    def report(self):
        required = os.environ.get(REQUIRE) == "1"
        try:
            from redfish_protocol_validator import report
        except ImportError as error:                       # pragma: no cover
            if required:
                pytest.fail(f"{REQUIRE}=1 and the protocol validator is not "
                            f"installed, so the only oracle for this reader "
                            f"could not run: {error}")
            pytest.skip("redfish-protocol-validator is not installed here; this "
                        "reader has no independent oracle in this environment")
        return report

    @pytest.mark.parametrize("failed,expected",
                             [(0, dmtf.CLEAN), (3, dmtf.REGRESSION)],
                             ids=["clean", "failures"])
    def test_the_reader_agrees_with_a_file_the_tool_wrote(self, report, tmp_path,
                                                          failed, expected):
        report.json_results(self._sut(failed), tmp_path,
                            datetime(2026, 1, 1, 0, 0, 0), "1.3.1")
        assert (tmp_path / dmtf.PROTOCOL_RESULTS).exists(), (
            "the tool no longer writes results.json under that name, which is "
            "the assumption this whole reader rests on")
        _service_report(tmp_path)
        verdict = dmtf.read(tmp_path, 0, int(failed > 0))
        assert verdict.exit_code == expected
        assert "40 check(s)" in verdict.detail
