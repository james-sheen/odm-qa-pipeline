"""The command line, which is what the templates actually call."""

from __future__ import annotations

import json

import pytest

from odm_qa_pipeline.cli import (EXIT_CLEAN, EXIT_INCOMPLETE, EXIT_REGRESSION,
                                 main)
from odm_qa_pipeline.gates import names


class TestPins:
    def test_it_lists_every_component(self, capsys):
        assert main(["pins"]) == EXIT_CLEAN
        out = capsys.readouterr().out
        assert "bmc-sensor-audit" in out
        assert "redfish-service-validator" in out

    def test_nothing_is_marked_unpinned_today(self, capsys):
        """Every component reached an index at 0.1.1, so this section is empty.
        It is asserted rather than left unmentioned: an absent warning and a
        warning nobody printed look identical from here."""
        main(["pins"])
        assert "* not pinned to a version:" not in capsys.readouterr().out

    def test_it_marks_and_explains_an_unpinned_one_when_there_is_one(
            self, capsys, monkeypatch):
        """The behaviour, proven against a synthetic manifest.

        It used to be proven against the shipped one, which worked only while
        something was actually unpinned -- so the day the last component was
        released, the check that the warning *works* would have disappeared
        along with the warning.
        """
        monkeypatch.setattr(
            "odm_qa_pipeline.cli.unpinned",
            lambda: {"example-tool": "tracks a branch while its name is decided"})
        main(["pins"])
        out = capsys.readouterr().out
        assert "* not pinned to a version:" in out
        assert "example-tool" in out
        assert "tracks a branch" in out

    def test_one_component_prints_one_line(self, capsys):
        assert main(["pins", "--component", "arbiter-engine"]) == EXIT_CLEAN
        assert capsys.readouterr().out.strip().startswith("arbiter-engine")

    def test_an_unknown_component_exits_two(self, capsys):
        assert main(["pins", "--component", "nope"]) == EXIT_INCOMPLETE

    def test_a_gate_prints_what_to_install(self, capsys):
        assert main(["pins", "--gate", "dmtf"]) == EXIT_CLEAN
        lines = capsys.readouterr().out.strip().splitlines()
        assert len(lines) == 2
        assert all("redfish" in line for line in lines)


class TestGates:
    def test_it_lists_them_in_order(self, capsys):
        assert main(["gates"]) == EXIT_CLEAN
        out = capsys.readouterr().out
        positions = [out.index(name) for name in names()]
        assert positions == sorted(positions), (
            "the gates printed out of order; order is the contract, since each "
            "gate answers a question the next one assumes")

    def test_each_one_says_what_a_failure_means(self, capsys):
        main(["gates"])
        assert capsys.readouterr().out.count("a non-zero exit means:") == len(names())


class TestRecordAndAggregate:
    def _record(self, tmp_path, gate, code):
        return main(["record", "--gate", gate, "--exit-code", str(code),
                     "--out", str(tmp_path / f"{gate}.json")])

    def test_a_full_clean_run_exits_zero(self, tmp_path):
        for gate in names():
            assert self._record(tmp_path, gate, 0) == EXIT_CLEAN
        assert main(["aggregate", "--results", str(tmp_path)]) == EXIT_CLEAN

    def test_a_missing_gate_exits_two(self, tmp_path, capsys):
        for gate in list(names())[:3]:
            self._record(tmp_path, gate, 0)
        assert main(["aggregate", "--results", str(tmp_path)]) == EXIT_INCOMPLETE
        assert "never reported" in capsys.readouterr().out

    def test_shell_assignments_work_without_files(self, capsys):
        argv = ["aggregate"] + [f"--gate={name}=0" for name in names()]
        assert main(argv) == EXIT_CLEAN

    def test_a_regression_exits_one(self):
        argv = ["aggregate"] + [f"--gate={name}=0" for name in names()[:-1]]
        argv.append(f"--gate={names()[-1]}=1")
        assert main(argv) == EXIT_REGRESSION

    def test_recording_an_unknown_gate_exits_two(self, tmp_path):
        assert main(["record", "--gate", "burn-in", "--exit-code", "0",
                     "--out", str(tmp_path / "x.json")]) == EXIT_INCOMPLETE

    def test_an_unreadable_results_directory_exits_two(self, tmp_path, capsys):
        assert main(["aggregate", "--results",
                     str(tmp_path / "absent")]) == EXIT_INCOMPLETE
        assert "could not aggregate" in capsys.readouterr().err

    def test_the_summary_is_written_when_asked(self, tmp_path):
        out = tmp_path / "summary.json"
        argv = ["aggregate", "--out", str(out)]
        argv += [f"--gate={name}=0" for name in names()]
        main(argv)
        summary = json.loads(out.read_text())
        assert summary["verdict"] == "clean"
        assert len(summary["gates"]) == len(names())

    def test_no_unpinned_note_appears_when_nothing_is_unpinned(self, capsys):
        argv = ["aggregate"] + [f"--gate={name}=0" for name in names()]
        main(argv)
        assert "track a branch, not a version" not in capsys.readouterr().out

    def test_the_unpinned_note_appears_on_every_run_when_there_is_one(
            self, capsys, monkeypatch):
        """Same reason as the `pins` pair: the note's whole point is to be
        unmissable, and a test that only fires while the manifest happens to
        carry an unpinned component stops testing it exactly when it is
        reintroduced."""
        monkeypatch.setattr("odm_qa_pipeline.cli.unpinned",
                            lambda: {"example-tool": "why"})
        argv = ["aggregate"] + [f"--gate={name}=0" for name in names()]
        main(argv)
        out = capsys.readouterr().out
        assert "track a branch, not a version" in out
        assert "example-tool" in out

    def test_optional_gates_are_accepted_from_the_command_line(self):
        argv = ["aggregate", "--optional", "certificate"]
        argv += [f"--gate={name}=0" for name in names()[:-1]]
        assert main(argv) == EXIT_CLEAN


class TestTheClosedGateSetExplainsItself:
    """A consumer meets this refusal before any explanation of it.

    Building a fifth gate against this package -- a fleet-drift gate over
    `fleet-sensor-baseline` -- ran into `record --gate fleet-drift` and stopped
    there. The set being closed is correct; the refusal saying only *that* it is
    closed is what made it look like an oversight.
    """

    def test_the_refusal_says_why_the_set_is_closed(self):
        from odm_qa_pipeline.gates import gate
        with pytest.raises(KeyError) as caught:
            gate("fleet-drift")
        message = str(caught.value)
        assert "never ran" in message, (
            "the refusal does not say what the closed set buys, so it reads as "
            "an arbitrary restriction")

    def test_the_cli_refusal_says_it_too(self, tmp_path, capsys):
        code = main(["record", "--gate", "fleet-drift", "--exit-code", "0",
                     "--detail", "x", "--out", str(tmp_path / "r.json")])
        assert code == EXIT_INCOMPLETE
        assert "never ran" in capsys.readouterr().err

    def test_a_declared_gate_is_still_accepted(self, tmp_path, capsys):
        """Non-vacuity: a refusal that refused everything would pass the two
        above and make the package useless."""
        out = tmp_path / "r.json"
        assert main(["record", "--gate", "coverage", "--exit-code", "0",
                     "--detail", "x", "--out", str(out)]) == EXIT_CLEAN
        assert out.is_file()
