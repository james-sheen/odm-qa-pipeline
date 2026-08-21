"""Every version constraint in the suite, read from one file.

The templates do not spell out a range and neither do the canaries; they ask this
module. A constraint written in a workflow *and* in a manifest is a constraint that
will drift, and the drift is invisible because both files look authoritative.

`tests/test_pins.py` reads the shipped workflow YAML and fails if a requirement
specifier appears in it. That is the check that keeps this file load-bearing rather
than merely present.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ["PinsError", "load", "requirement", "requirements_for", "unpinned",
           "PINS_PATH"]

# Inside the package, deliberately. At the repository root it would resolve
# through `../../` -- correct from a checkout and pointing outside site-packages
# once installed, so the manifest would simply not be found by the people who
# installed the tool. Shipping a second copy alongside would be worse: two files,
# one fact, guaranteed to disagree eventually.
PINS_PATH = Path(__file__).resolve().parent / "pins.json"

_cache: dict | None = None


class PinsError(ValueError):
    """The pin manifest cannot be used."""


def load(path: Path | str | None = None) -> dict:
    global _cache
    if path is None and _cache is not None:
        return _cache

    target = Path(path) if path else PINS_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise PinsError(f"no pin manifest at {target}") from error
    except json.JSONDecodeError as error:
        raise PinsError(f"{target} is not valid JSON: {error}") from error

    components = raw.get("components")
    if not isinstance(components, dict) or not components:
        raise PinsError(f"{target} declares no components")

    for name, entry in components.items():
        if not isinstance(entry, dict) or not entry.get("requirement"):
            raise PinsError(f"{name} carries no 'requirement'")
        if not entry.get("published", False) and not entry.get("why_unpinned"):
            # An unpinned component is a real risk and the manifest must say what
            # it is. Left blank, the entry looks identical to a pinned one at a
            # glance, which is how a branch reference survives into production.
            raise PinsError(
                f"{name} is not published and carries no 'why_unpinned'; an "
                f"unpinned component must state what it costs")

    if path is None:
        _cache = raw
    return raw


def requirement(name: str, path: Path | str | None = None) -> str:
    components = load(path)["components"]
    if name not in components:
        raise PinsError(f"no component named {name!r}; the manifest declares "
                        f"{', '.join(sorted(components))}")
    return components[name]["requirement"]


def requirements_for(gate: str, path: Path | str | None = None) -> list[str]:
    """Everything a single gate needs installed, in manifest order."""
    return [entry["requirement"]
            for entry in load(path)["components"].values()
            if entry.get("gate") == gate]


def unpinned(path: Path | str | None = None) -> dict[str, str]:
    """Components tracking something that is not a version, and why.

    Surfaced by the CLI on every run rather than buried in a file, because a
    pipeline whose inputs can change between two identical invocations should say
    so out loud each time.
    """
    return {name: entry["why_unpinned"]
            for name, entry in load(path)["components"].items()
            if not entry.get("published", False)}


def describe(path: Path | str | None = None) -> list[dict[str, Any]]:
    rows = []
    for name, entry in load(path)["components"].items():
        rows.append({"component": name,
                     "gate": entry.get("gate"),
                     "requirement": entry["requirement"],
                     "published": bool(entry.get("published", False)),
                     "role": entry.get("role", "")})
    return rows
