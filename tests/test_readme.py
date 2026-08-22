"""The README is the one surface that can promise what no index can deliver.

`bmc-sensor-audit` already carries a pair like this -- its README and its CITATION
file each have to agree with the released state -- but both are anchored on a
version sentinel, `__version__ == "0.0.0"`. That does not transplant here. This
package declares a real `0.1.0` and is on no index, so the sentinel reads
*released*, the check passes, and the README goes on sending readers to a name
PyPI answers 404 for. A mechanism copied without its premise is a check that runs
correctly and asks the wrong question.

The fact that *is* true locally is the one the templates already act on. Both
shipped templates default `PIPELINE_REQUIREMENT` to a `git+https` direct
reference, because there is nothing to install from an index yet. So the machine-
read surface of this repo and the human-read one disagreed about where the
umbrella comes from, and the wrong one was the one a person meets first.
`test_pins.py` guards a version written in two places; this guards an install
form written in two places, which is the same disease in another currency.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from odm_qa_pipeline import __version__

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
DIST = "odm-qa-pipeline"

UNRELEASED = "Not yet released"

# The wording `bmc-sensor-audit` announces a release with. Reused verbatim rather
# than invented, so this family has one vocabulary for one fact and a future
# release here needs no new spelling.
RELEASED = re.compile(r"\*\*Released[^*]*?(\d+\.\d+\.\d+)\*\*")

# `pip install odm-qa-pipeline`, quoted or not, with or without an extra -- the
# form that only works once an index carries the name. The lookahead is what makes
# it usable while unreleased: `pip install "odm-qa-pipeline @ git+https://..."` is
# a direct reference, not an index lookup, and must not trip this.
#
# Spelled strictly, for the reason `test_pins.py` records at length: a guard with
# false positives is a guard the next person loosens.
INDEX_INSTALL = re.compile(
    r"pip install\s+(?:-[^\s]+\s+)*['\"]?"
    + re.escape(DIST)
    + r"(?:\[[A-Za-z0-9,_\-]+\])?['\"]?(?!\s*@)")

TEMPLATES = (ROOT / "templates" / "github" / "odm-qa.yml",
             ROOT / "templates" / "jenkins" / "Jenkinsfile")


def _tags():
    """Repository tags, or None when git cannot answer -- borrowed from
    `bmc-sensor-audit`, caveat included. A checkout with no `.git` exits
    non-zero and an image with no git binary raises; answering `[]` for either
    would turn *cannot tell* into *there are no tags*. A shallow clone fetched
    without tags answers successfully and is still not an answer.
    """
    try:
        listed = subprocess.run(["git", "tag"], cwd=str(ROOT),
                                capture_output=True, text=True)
    except OSError:
        return None
    if listed.returncode != 0:
        return None
    return [line for line in listed.stdout.split() if line]


class TestTheReadmeDoesNotPromiseAnIndex:

    def test_the_readme_states_a_release_state_at_all(self):
        """Non-vacuity, and it is the whole reason this file is not one test.

        Every rule below is conditional on one of these two markers being
        present. Without this, deleting the marker is a way to pass -- the
        prohibition would find nothing and report success, which is the failure
        shape this suite refuses everywhere else.
        """
        readme = README.read_text()
        unreleased = UNRELEASED in readme
        released = RELEASED.search(readme)
        assert unreleased or released, (
            "the README states neither that this is unreleased nor which version "
            f"was released; one of `{UNRELEASED}` or `**Released -- X.Y.Z**` has "
            "to be there for the rest of this file to mean anything")
        assert not (unreleased and released), (
            "the README says both that this is unreleased and that a version was "
            "released; that is two answers to one question")

    def test_an_index_install_is_not_offered_while_unreleased(self):
        readme = README.read_text()
        if UNRELEASED not in readme:
            return
        found = INDEX_INSTALL.search(readme)
        assert not found, (
            f"the README says {UNRELEASED.lower()} and still tells a reader "
            f"{found.group(0)!r}; that command resolves against an index which "
            f"does not carry this name. Offer the direct reference the templates "
            f"already default to, or release it")

    def test_a_released_readme_names_the_version_the_package_reports(self):
        """The other branch, so this file keeps working after publication rather
        than becoming a check that only ever meant something once."""
        readme = README.read_text()
        released = RELEASED.search(readme)
        if not released:
            return
        assert released.group(1) == __version__, (
            f"the README announces {released.group(1)} and the package reports "
            f"{__version__}; both are published records of one fact")

    def test_an_announced_release_has_a_tag_behind_it(self):
        """Otherwise the cheapest way past this file is to announce a release
        that did not happen: the version matches because both come from the tree.
        A tag is the one part of the claim the tree cannot write about itself.
        """
        released = RELEASED.search(README.read_text())
        if not released:
            return
        tags = _tags()
        if not tags:
            pytest.skip("no tags visible here; *cannot tell* is not *no tags*")
        assert f"v{released.group(1)}" in tags, (
            f"the README announces {released.group(1)} and no tag v"
            f"{released.group(1)} exists; a release nobody tagged is a claim "
            f"with nothing behind it")

    def test_the_matcher_finds_a_bare_install_when_there_is_one(self):
        """The prohibition above is only worth as much as the pattern under it."""
        assert INDEX_INSTALL.search(f"pip install {DIST}")
        assert INDEX_INSTALL.search(f"pip install '{DIST}[dev]'")
        assert INDEX_INSTALL.search(f"pip install --quiet {DIST}")
        assert not INDEX_INSTALL.search(
            f'pip install "{DIST} @ git+https://example.invalid/x@master"')
        assert not INDEX_INSTALL.search("pip install -r requirements-coverage.txt")
        assert not INDEX_INSTALL.search("pip install -e .")


class TestTheReadmeAndTheTemplatesAgree:
    """Where the umbrella comes from is one fact with two audiences. The templates
    are consumed by a pipeline and the README by a person, and only the person
    was being told something untrue."""

    def test_every_template_names_the_umbrella(self):
        for path in TEMPLATES:
            assert DIST in path.read_text(), (
                f"{path.name} never names {DIST}, so the agreement checked below "
                f"would hold by finding nothing")

    def test_they_agree_about_where_it_comes_from(self):
        readme = README.read_text()
        for path in TEMPLATES:
            from_git = f"{DIST} @ git+" in path.read_text()
            offered = INDEX_INSTALL.search(readme)
            if from_git:
                assert not offered, (
                    f"{path.name} installs the umbrella from git and the README "
                    f"tells a reader {offered.group(0)!r}; one of them is wrong "
                    f"about whether this name is on an index")
            else:
                assert offered, (
                    f"{path.name} no longer installs from git, so this is on an "
                    f"index -- and the README does not say so")
