"""The four gates, actually run, against a mock BMC.

Everything else here tests this package in isolation, which is correct and is not
enough: the product is a *composition*, and a composition can be wrong while every
part of it is right. A gate whose CLI grew a flag, an exit code that changed
meaning, an artifact one tool writes and the next cannot read -- none of that is
visible from inside this repository.

So this installs nothing and assumes nothing. If the suite is on `PATH` it runs
three of the four gates for real and checks the verdict. If it is not, it says so
and skips -- except in CI, where `ODM_QA_REQUIRE_COMPOSITION=1` makes the skip a
failure, because the composition test not running is indistinguishable from the
composition working unless somebody is watching the skip count.

**Gate 1 is not run.** DMTF's validators need a Redfish service far more complete
than a mock, and pretending otherwise would be a gate that passes because it was
pointed at something too small to fail. It is declared optional here and that
declaration is on the record, which is the distinction this whole package is about.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from odm_qa_pipeline.aggregate import CLEAN, INCOMPLETE, REGRESSIONS

REQUIRED = os.environ.get("ODM_QA_REQUIRE_COMPOSITION") == "1"

TOOLS = ("bmc-sensor-audit", "qa-orchestrator", "cert-generator",
         "odm-qa-pipeline")

BOARD = {"Name": "Reference Board", "Exposes": [
    {"Name": "Inlet Temp", "Type": "TMP75", "Thresholds": [
        {"Name": "upper critical", "Severity": 1,
         "Direction": "greater than", "Value": 80},
        {"Name": "upper warning", "Severity": 0,
         "Direction": "greater than", "Value": 70}]},
    # Declared and never served, so gate 2 has a real regression to find.
    {"Name": "Fan 3 Tach", "Type": "AspeedFan", "Thresholds": [
        {"Name": "lower critical", "Severity": 1,
         "Direction": "less than", "Value": 500}]}]}


def _require(reason: str):
    if REQUIRED:
        pytest.fail(reason + " -- and this run requires the composition test")
    pytest.skip(reason)


@pytest.fixture(scope="module")
def suite():
    missing = [tool for tool in TOOLS if shutil.which(tool) is None]
    if missing:
        _require(f"not on PATH: {', '.join(missing)}; the composition was never "
                 f"exercised and nothing here was checked")
    try:
        import arbiter_engine  # noqa: F401
    except ImportError:
        _require("arbiter-engine is not installed, so gate 2 cannot reach "
                 "Stage 2; install what `odm-qa-pipeline pins --gate coverage` "
                 "prints")
    try:
        from bmc_sensor_audit.testing.mock_redfish import MockBMC  # noqa: F401
    except ImportError:
        _require("the audit tool's mock BMC is not importable")
    return True


@pytest.fixture(scope="module")
def workspace(suite, tmp_path_factory):
    """Run the three runnable gates once; every test reads the same results."""
    from bmc_sensor_audit.testing.mock_redfish import MockBMC, MockSensor, serve

    root = tmp_path_factory.mktemp("composition")
    (root / "qa-results").mkdir()
    (root / "qa-artifacts").mkdir()
    (root / "board.json").write_text(json.dumps(BOARD))
    (root / "identity.json").write_text(json.dumps(
        {"serial": "SN-COMPOSITION-1", "work_order": "WO-CI",
         "station": "CI", "signer": "the suite"}))

    def run(args, cwd=None):
        return subprocess.run([str(a) for a in args], cwd=cwd or root,
                              capture_output=True, text=True)

    def record(gate, code, detail):
        assert run(["odm-qa-pipeline", "record", "--gate", gate,
                    "--exit-code", str(code), "--detail", detail,
                    "--out", f"qa-results/{gate}.json"]).returncode == 0

    bmc = MockBMC(shape="sensors")
    bmc.sensors.append(MockSensor(name="Inlet Temp", reading=92.4,
                                  upper_critical=80.0, upper_warning=70.0))

    outcome = {}
    with serve(bmc) as url:
        detect = run(["bmc-sensor-audit", "detect", "--config", "board.json",
                      "--target", url,
                      "--attest-out", "qa-artifacts/attestation.json",
                      "--attest-target-label", "unit-under-test"])
        coverage = run(["bmc-sensor-audit", "coverage", "--config", "board.json",
                        "--target", url, "--json"])
        (root / "qa-artifacts" / "coverage.json").write_text(coverage.stdout)
        outcome["coverage"] = max(detect.returncode, coverage.returncode)
        record("coverage", outcome["coverage"],
               f"detect {detect.returncode}, coverage {coverage.returncode}")

    certificate = run(["cert-generator", "render",
                       "--attestation", "qa-artifacts/attestation.json",
                       "--coverage", "qa-artifacts/coverage.json",
                       "--identity", "identity.json",
                       "--out-json", "qa-artifacts/certificate.json",
                       "--out-pdf", "qa-artifacts/certificate.pdf"])
    outcome["certificate"] = certificate.returncode
    record("certificate", certificate.returncode, "from the gate 2 attestation")
    outcome["root"] = root
    outcome["run"] = run
    return outcome


class TestTheArtifactsCross:
    def test_gate_two_produced_both_artifacts(self, workspace):
        root = workspace["root"]
        assert (root / "qa-artifacts" / "attestation.json").stat().st_size > 0
        assert (root / "qa-artifacts" / "coverage.json").stat().st_size > 0

    def test_gate_two_found_the_absent_sensor(self, workspace):
        coverage = json.loads(
            (workspace["root"] / "qa-artifacts" / "coverage.json").read_text())
        assert coverage["counts"]["declared_absent"] == 1
        assert workspace["coverage"] == REGRESSIONS

    def test_gate_four_read_what_gate_two_wrote(self, workspace):
        """The seam. Two separately released tools, one artifact between them."""
        certificate = json.loads(
            (workspace["root"] / "qa-artifacts" / "certificate.json").read_text())
        assert certificate["judgment"]["finding_count"] >= 1
        # Two, because BOARD declares two sensors: the one that reports and the
        # one that never does. The point is that this number came out of gate 2
        # and reached gate 4 -- the attestation alone does not carry it.
        assert certificate["not_part_of_this_judgment"][
            "declaration_diff"]["declared"] == len(BOARD["Exposes"]), (
            "the certificate did not carry the declaration diff gate 2 produced")

    def test_gate_four_names_the_unit_gate_two_never_saw(self, workspace):
        certificate = json.loads(
            (workspace["root"] / "qa-artifacts" / "certificate.json").read_text())
        attestation = json.loads(
            (workspace["root"] / "qa-artifacts" / "attestation.json").read_text())
        assert certificate["identity"]["serial"] == "SN-COMPOSITION-1"
        assert "SN-COMPOSITION-1" not in json.dumps(attestation), (
            "the serial reached the audit artifact; identity must flow only "
            "toward the certificate")

    def test_the_certificate_rendered(self, workspace):
        pdf = workspace["root"] / "qa-artifacts" / "certificate.pdf"
        assert pdf.read_bytes()[:5] == b"%PDF-"


class TestTheVerdict:
    def test_a_gate_that_never_ran_makes_it_incomplete(self, workspace):
        result = workspace["run"](["odm-qa-pipeline", "aggregate",
                                   "--results", "qa-results"])
        assert result.returncode == INCOMPLETE
        assert "gates that never reported" in result.stdout
        assert "dmtf" in result.stdout
        assert "injection" in result.stdout

    def test_declaring_them_optional_lets_the_findings_decide(self, workspace):
        result = workspace["run"](["odm-qa-pipeline", "aggregate",
                                   "--results", "qa-results",
                                   "--optional", "dmtf",
                                   "--optional", "injection"])
        assert result.returncode == REGRESSIONS, result.stdout
        assert "coverage" in result.stdout

    def test_the_unpinned_warning_reaches_the_operator(self, workspace):
        result = workspace["run"](["odm-qa-pipeline", "aggregate",
                                   "--results", "qa-results",
                                   "--optional", "dmtf",
                                   "--optional", "injection"])
        assert "track a branch, not a version" in result.stdout


class TestTheInjectionGate:
    """Run separately: the orchestrator serves its own machine, so it needs no
    target from us -- but it does need the referee on PATH, and its refusal when
    that is missing is worth pinning."""

    def test_the_shipped_scenarios_parse_and_run(self, workspace):
        named = os.environ.get("ODM_QA_SCENARIOS")
        if not named:
            _require("no scenario directory given; set ODM_QA_SCENARIOS to the "
                     "orchestrator's scenarios/ to exercise gate 3")
        # Resolved against pytest's own working directory, because the gates run
        # from a temporary workspace and a relative value would vanish there.
        # `ODM_QA_SCENARIOS=qa-orchestrator/scenarios` is the natural thing to
        # write in a workflow and it must keep working -- the caller should not
        # have to know where this test chooses to run subprocesses.
        scenarios = Path(named).resolve()
        if not scenarios.is_dir():
            _require(f"ODM_QA_SCENARIOS names {scenarios}, which is not a "
                     f"directory; gate 3 was not exercised")

        parse = workspace["run"](["qa-orchestrator", "check", str(scenarios)])
        assert parse.returncode == CLEAN, parse.stdout + parse.stderr
        run = workspace["run"](["qa-orchestrator", "run",
                                str(scenarios / "stuck-at.yaml")])
        assert run.returncode == CLEAN, run.stdout + run.stderr
