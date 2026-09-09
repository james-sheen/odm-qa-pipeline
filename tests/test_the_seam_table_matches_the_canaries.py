"""The README's seam table and the workflow matrix are two records of one set.

This repository's manifest exists because *a number written in two places is a
number that will disagree with itself and no check will notice*. The seam list
was exactly that, in two files, and it had already drifted in the way that
costs the most: the row for the orchestrator's tier interface described a
module the orchestrator's 0.3 rewrite deleted, naming three tiers it has never
shipped. The canary's own check was corrected when that happened. The sentence
describing it was not, and an outside reviewer read the table, believed it, and
returned those names to us as findings.

So the two records are held to each other here, in both directions, and the
COUNT is stated in neither -- it was written out in the README and again in the
workflow header, which is a third and fourth copy of the same fact.

What this cannot check is whether a contract sentence is TRUE of the job it
labels; only that every job has one and every one is claimed. A description
that is wrong about a real check is still possible, and it is what happened.
"""

from __future__ import annotations

import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml", reason="the workflow is YAML; CI installs PyYAML")

ROOT = pathlib.Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
WORKFLOW = ROOT / ".github" / "workflows" / "seam-canaries.yml"


def _matrix_seams() -> dict:
    """seam id -> the contract string the workflow labels the job with."""
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    include = data["jobs"]["seam"]["strategy"]["matrix"]["include"]
    return {entry["seam"]: entry.get("contract", "") for entry in include}


def _table_seams() -> dict:
    """seam label -> contract, from the README's table."""
    found = re.search(r"^\| seam \| contract \|\n\|[-|]+\|\n((?:\|.*\n)+)",
                      README, re.M)
    if not found:
        return {}
    rows = {}
    for line in found.group(1).strip().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 2:
            rows[cells[0]] = cells[1]
    return rows


def _as_id(label: str) -> str:
    """`cert-gen -> tool` reads as `certgen-tool` in the matrix. The arrow is
    the separator and everything else is the job id with its punctuation
    dropped -- derived, so a new row needs no edit here."""
    left, _, right = label.partition("→")
    squash = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    return f"{squash(left)}-{squash(right)}"


class TestEverySeamAppearsInBothRecords:

    def test_there_are_seams_to_compare(self):
        """NON-VACUITY. Both derivations are regex and YAML lookups over files
        that can be restructured; either returning nothing turns every check
        below into a comparison of two empty sets, which is a pass."""
        assert _matrix_seams(), "no seams parsed out of the workflow matrix"
        assert _table_seams(), "no rows parsed out of the README's seam table"

    def test_the_two_records_name_the_same_set(self):
        matrix = set(_matrix_seams())
        table = {_as_id(label) for label in _table_seams()}
        assert matrix == table, (
            f"the workflow runs {sorted(matrix - table)} that the README's "
            f"table does not list, and the table lists "
            f"{sorted(table - matrix)} that no job runs. A canary nobody can "
            f"find in the table is one nobody looks at; a row with no job "
            f"behind it is a contract nothing checks")

    def test_the_id_derivation_can_actually_fail(self):
        """The comparison above is only as good as the mapping under it: a
        derivation that squashed everything to one string would make the two
        sets agree by collapsing them."""
        assert _as_id("cert-gen → tool") == "certgen-tool"
        assert _as_id("core → engine") == "core-engine"
        assert _as_id("a → b") != _as_id("c → d")

    @pytest.mark.parametrize("seam", sorted(_matrix_seams()))
    def test_every_job_says_what_it_checks(self, seam):
        """A job whose step has no contract line runs under its own id, and
        the log then says only which seam went red, not what it was for."""
        contract = _matrix_seams()[seam]
        assert contract and len(contract) > 15, (
            f"the {seam} job carries the contract label {contract!r}, which "
            f"is what a reader of a red run sees first")


class TestTheCountIsStatedNowhere:
    """It was stated in the README and again in the workflow header. Adding a
    seam then meant editing four places, and the two that were prose went
    stale silently -- which is the same failure the table itself had."""

    WORDS = ("four", "five", "six", "seven", "eight")

    @pytest.mark.parametrize("where", ["README.md", ".github/workflows/seam-canaries.yml"])
    def test_no_file_writes_the_number_of_seams_out(self, where):
        text = (ROOT / where).read_text(encoding="utf-8").lower()
        offenders = [word for word in self.WORDS if f"{word} seams" in text]
        assert offenders == [], (
            f"{where} states the seam count as {offenders}. The count is "
            f"derivable from the matrix and is one more thing to update; the "
            f"test above already holds the two lists to each other")

    def test_the_predicate_would_see_such_a_sentence(self):
        """Before believing a negative, prove the probe can produce a positive.
        The sentence this check exists to have caught, run through it."""
        was = "Five seams join these components, and each has a daily canary"
        assert [w for w in self.WORDS if f"{w} seams" in was.lower()], (
            "the predicate cannot see the sentence it was written for")
