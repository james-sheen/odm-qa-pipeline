"""The umbrella: four gates in order, one exit code, and no silent pass.

This package composes tools it does not own. It contributes exactly two things
that none of them can contribute for themselves:

- **an aggregate verdict** across gates, under the rule that could-not-complete
  never reads as clean; and
- **the observation that a gate did not run**, which no gate can report about
  itself, because a program that did not start emits nothing at all.

The version lives here and nowhere else; `pyproject.toml` reads it.
"""

__version__ = "0.1.1"

RESULT_FORMAT = "odm-qa-pipeline/gate-result/1"
SUMMARY_FORMAT = "odm-qa-pipeline/summary/1"

__all__ = ["__version__", "RESULT_FORMAT", "SUMMARY_FORMAT"]
