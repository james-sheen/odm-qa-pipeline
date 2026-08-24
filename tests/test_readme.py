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


# **The ANCHOR for every version record in this repository.** `pyproject.toml`
# reads the literal for packaging, so it is the one record that cannot disagree
# with the artifact -- and the only one that answers in an sdist and in a shallow
# checkout with no tags. Everything else is compared against it, never against
# another derivation of it.
NO_RELEASE = "0.0.0"

#: The tag the README's Status line names, so the two can be compared without
#: asking git anything.
TAGGED = re.compile(r"tagged `([^`]+)`")

#: The tag namespace this project releases in: `v` and a dotted version.
_TOOL_TAG = re.compile(r"^v(\d+(?:\.\d+)*)$")


def _released_versions(tags):
    """Every tag naming a version of THIS package, as comparable tuples."""
    return [tuple(int(part) for part in match.group(1).split("."))
            for match in (_TOOL_TAG.match(tag) for tag in tags) if match]


def _named_tag():
    """The tag string the README's Status line names, or None."""
    found = TAGGED.search(README.read_text())
    return found.group(1) if found else None


def _version():
    from odm_qa_pipeline import __version__
    return __version__


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

    def test_the_readme_names_the_tag_this_version_will_carry(self):
        """The tag string and the version literal, compared without asking git.

        **The anchor is the version LITERAL.** It is what the package reports
        about itself, what `pyproject.toml` reads for packaging, and the only one
        of these records that answers in an sdist and in a shallow checkout with
        no tags. Every other record is derived from it, so every other record is
        compared against it rather than against another derivation.

        The Status line carries a tag string that nothing used to check, so a
        `v0.1.1` left behind by a bump to 0.1.2 sent a reader to a tag describing
        different code -- and both strings look right in isolation.

        Tree-local, so it holds at every instant of a release. The check below
        cannot say that of itself.
        """
        version = _version()
        named = _named_tag()
        if version == NO_RELEASE:
            assert named is None, (
                f"the README names the tag {named!r} while the package reports "
                f"{NO_RELEASE}; an unreleased tree must not hand a reader a tag "
                f"to check out")
            return
        assert named, (
            f"the package reports {version} and the README names no tag. The "
            f"Status line should read: tagged `v{version}`")
        assert named == f"v{version}", (
            f"the README names the tag {named!r} and the package reports "
            f"{version}; they must be `v{version}`. A leading v dropped from one, "
            f"or a tag string left behind by a bump, is how these two part company")

    def test_a_tag_and_the_tree_do_not_disagree(self):
        """A tag is the one part of the claim the tree cannot write about itself.

        **What was wrong with this before.** It tolerated only a repository with
        NO TAGS AT ALL -- true when written, false forever after the first
        release. The tag is made OF the commit that bumps the version, so from
        then on it went red between the bump and the tag, every release, at the
        moment somebody is most likely to reach for `--no-verify`.

        Worse than red, it RACED. CI fetches whatever tags the remote holds at
        checkout and a release pushes master before the tag, so a release
        commit's own CI run passed or failed on which push won.

        **The window is carved to the rule rather than widened.** Only this
        version may be untagged, and only while no LATER version is tagged: a
        release in flight is always the newest one. A reverted bump that left its
        tag, or a tag made from the wrong commit, both leave a later tag behind
        and still fail here.

        Whether the tag was ever PUSHED is a fact about the remote, and no
        assertion from a working tree can reach it. Saying so is the honest
        version; asserting it would be a check that is right by luck.
        """
        tags = _tags()
        if not tags:
            pytest.skip("no tags visible here; *cannot tell* is not *no tags*")
        version = _version()
        assert version != NO_RELEASE, (
            f"the repository has tags {tags} and the package still reports "
            f"{NO_RELEASE}")
        if f"v{version}" in tags:
            return
        current = tuple(int(part) for part in version.split("."))
        ahead = sorted(t for t in _released_versions(tags) if t > current)
        assert not ahead, (
            f"v{version} has no tag, and "
            f"{['v' + '.'.join(map(str, t)) for t in ahead]} name later versions. "
            f"A release in flight is the only reason this version should be "
            f"untagged, and a release in flight is always the newest one -- so "
            f"either a bump was reverted with its tag left behind, or a tag was "
            f"made from the wrong commit")
        pytest.skip(
            f"v{version} is not tagged in this tree. The tag is made OF the "
            f"commit that sets the version literal, so this is the one legitimate "
            f"window and `git tag -a v{version}` closes it. Whether the tag was "
            f"ever pushed is a fact about the remote rather than this tree.")

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
