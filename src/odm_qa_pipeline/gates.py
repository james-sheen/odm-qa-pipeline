"""The four gates, declared once, in the order they run.

Order is not decoration. Each gate answers a question the next one assumes, so
running them out of order produces confident answers to questions that were never
established:

1. **dmtf** -- does this machine speak Redfish correctly at all? Everything
   downstream reads Redfish; if the protocol is wrong, a sensor "missing" may
   simply be a response nobody could parse.
2. **coverage** -- of the sensors the configuration declares, which are present,
   and did that change across the firmware under test?
3. **injection** -- when a fault is introduced deliberately, does the referee
   notice? This is the only gate that tests the *tooling* rather than the machine.
4. **certificate** -- render what was established, including what was not.

A gate may be skipped by declaring it optional. It may not be skipped by silence:
see `aggregate.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Gate", "GATES", "gate", "names"]


@dataclass(frozen=True)
class Gate:
    name: str
    question: str
    supplied_by: tuple[str, ...]
    #: What a non-zero exit from this gate means, in the operator's terms.
    regression_means: str


GATES: tuple[Gate, ...] = (
    Gate(
        name="dmtf",
        question="does the machine conform to the Redfish schema and protocol?",
        supplied_by=("redfish-service-validator", "redfish-protocol-validator"),
        regression_means="the machine's Redfish implementation is out of "
                         "conformance; readings downstream may be unparseable "
                         "rather than absent",
    ),
    Gate(
        name="coverage",
        question="which declared sensors are present, and did that change?",
        supplied_by=("bmc-sensor-audit", "arbiter-engine"),
        regression_means="a sensor the configuration declares stopped being "
                         "reported, or stopped varying",
    ),
    Gate(
        name="injection",
        question="when a fault is introduced on purpose, does the referee catch it?",
        supplied_by=("qa-orchestrator",),
        regression_means="the audit tool did not reach the verdict a known fault "
                         "should produce; the tooling is wrong, not the machine",
    ),
    Gate(
        name="certificate",
        question="can a certificate be rendered from what was established?",
        supplied_by=("odm-cert-generator",),
        regression_means="the unit has findings recorded against it, or a "
                         "declared sensor was absent",
    ),
)


def names() -> tuple[str, ...]:
    return tuple(g.name for g in GATES)


def gate(name: str) -> Gate:
    for candidate in GATES:
        if candidate.name == name:
            return candidate
    raise KeyError(
        f"no gate named {name!r}; this pipeline runs {', '.join(names())}. "
        f"The set is closed on purpose: `aggregate` can only report a gate "
        f"that never ran because it knows which gates were expected, and a "
        f"name it has never heard of is indistinguishable from a typo in one "
        f"it has. Adding a gate is a change to this package -- it needs a "
        f"position in the order above and a declared question -- not a string "
        f"a caller invents")
