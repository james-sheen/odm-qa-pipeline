# odm-qa-pipeline

Four QA gates, in order, and one verdict from them.

**Released — 0.1.0**, tagged `v0.1.0`, Apache-2.0, on PyPI as `odm-qa-pipeline`.

```
pip install odm-qa-pipeline

odm-qa-pipeline gates            # what runs, and what a failure in each means
odm-qa-pipeline pins             # every version constraint, from one file
odm-qa-pipeline aggregate --results qa-results
```

## The gates

| | gate | asks | supplied by |
|---|---|---|---|
| 1 | `dmtf` | does the machine conform to the Redfish schema and protocol? | DMTF's own validators |
| 2 | `coverage` | which declared sensors are present, and did that change? | `bmc-sensor-audit` |
| 3 | `injection` | when a fault is introduced on purpose, does the referee catch it? | `qa-orchestrator` |
| 4 | `certificate` | can a certificate be rendered from what was established? | `cert-generator` |

The order is the contract. Each gate answers a question the next one assumes: if
the Redfish implementation is out of conformance, a "missing" sensor downstream may
be a response nobody could parse. Gate 3 is the only one that tests the *tooling*
rather than the machine.

## What this package adds

It composes tools it does not own, and contributes exactly two things none of them
can contribute for themselves.

**An aggregate verdict**, under the rule the whole suite is built on: `0` clean,
`1` regressions, `2` could not complete — and `2` never reads as clean. Precedence
is `max`. A run that both found a regression and failed to finish reports `2`,
because `2` is the statement about the denominator and `1` would let a reader
conclude the rest was checked.

**The observation that a gate did not run.** This is the one worth the package.
Every tool here is careful about could-not-complete, and not one of them can tell
you it was never invoked — a program that did not start emits no exit code at all.
Somebody has to hold the list of what was supposed to happen and compare:

```
pipeline: incomplete (exit 2)
  dmtf         clean
  coverage     clean
  injection    incomplete -- this gate reported nothing at all. A gate that did not run has not passed
  certificate  clean
  gates that never reported: injection
```

A pipeline where the injection step was commented out six weeks ago and every run
since came back green is the failure this exists to prevent.

A gate may be declared optional with `--optional <gate>`, which is a decision on the
record. It may not be skipped by silence.

## An exit code nobody defined

A gate that dies on `command not found` exits `127`. Taking `max` over raw codes
would return a number from a vocabulary this suite does not use, so anything outside
`{0, 1, 2}` is read as `2` and the raw code is kept beside it — *"exited 127"* is the
useful half of that sentence.

## The verdict here is not the certificate

Two records run in parallel and neither contains the other. `aggregate` answers
whether all four gates ran and what the worst thing any of them found was. The
certificate `cert-generator` renders answers what the referee established about one
unit — attestation, identity, and the declaration diff when supplied — and carries
nothing from gate 1 or gate 3.

Worth stating because reading either as the other goes wrong in both directions: a
clean certificate says nothing about whether the injection gate ran, and a clean
verdict here is not a document anyone can hand to a customer.

## Templates, not a framework

Two composition templates ship here. Copy them; do not wrap them.

- `templates/github/odm-qa.yml` — a reusable workflow (`workflow_call`)
- `templates/jenkins/Jenkinsfile` — the same four gates for a Jenkins agent

Both share the two properties that matter, and both are tested as artifacts in
this repository's own CI rather than trusted as prose:

- **No version is written in either.** Every requirement comes from
  `odm-qa-pipeline pins`. A range spelled out in a workflow as well is a second
  copy of one fact, and the two would disagree the first time either moved —
  silently, because both files look authoritative. `tests/test_pins.py` fails if a
  requirement specifier appears in any shipped definition.

  Its output is a **requirements file**, one per line, and must be consumed as
  one:

  ```
  odm-qa-pipeline pins --gate coverage > requirements-coverage.txt
  pip install -r requirements-coverage.txt
  ```

  Not `pip install $(odm-qa-pipeline pins --gate coverage)`. A direct reference
  such as `qa-orchestrator @ git+https://…` contains spaces; the shell splits it
  into three arguments and pip stops on the bare `@`. That is a real defect this
  repository shipped and CI caught — nothing in the suite saw it, because every
  test read the manifest through Python and never through a shell.
- **Every gate records a result, including the ones that fail**, and the
  aggregation runs under `if: always()` / `post { always }`. Skipping the summary
  when a gate fails would mean the aggregate verdict existed only for runs that
  went well.

Inputs reach the shell through `env:`, never `${{ }}` interpolated into a `run:`
block — GitHub substitutes those before bash parses the line, so a target URL
containing a backtick would execute.

## One canary per seam

Five seams join these components, and each has a daily canary in
`.github/workflows/seam-canaries.yml`:

| seam | contract |
|---|---|
| tool → engine | pin range; envelope `schema_version: 1` |
| orchestrator → tool | exit codes 0/1/2; report JSON; `walk/1` |
| orchestrator → firmware | the `mock` / `qemu` / `testbed` backend interface |
| cert-gen → tool | `attestation/1` via the tool's shipped validator |
| pipeline → all | every pin in the manifest still resolves |

Two repositories in this family have watched a workflow sit red-or-silent for want
of exactly this. The failure mode that matters is not a canary going red; it is a
canary quietly passing because it stopped checking.

## One component is not pinned, and the manifest says why

`cert-generator` is not on any index, so the manifest tracks its default branch.
**A branch is not a pin**: the same pipeline definition can resolve to different
code on two consecutive days and nothing here would report a difference.

The reason is specific rather than pending. PyPI ultranormalises a distribution
name by stripping the separators, so `cert-generator` becomes `certgenerator` —
which an unrelated project holds — and the upload is refused as *too similar to an
existing project*. That is a name decision, not a packaging one: the repository,
the import package and the `cert-generator` command are unaffected.

That is stated in `pins.json` per component, enforced by a test — an unpublished
component without a `why_unpinned` reason is refused — and printed on every
`aggregate` run rather than left in a file nobody opens.

## The DMTF gate is adopted, not built

Redfish schema and protocol conformance is DMTF's own published tooling
(`rf_service_validator`, `rf_protocol_validator`). This suite runs them as a
sibling gate and contributes nothing to that problem, deliberately. What it adds
is the two things those validators do not do: the declaration diff and liveness.

Their tools do not use this suite's three-code vocabulary, so a conformance failure
and a service the validator could not reach return the same thing — and the service
validator has already written its debug log by then. Scoring on *some file exists*
therefore recorded an unreachable BMC as a regression against the machine: a `2`
reported as a `1`, in the one gate this suite borrows rather than builds.

`odm-qa-pipeline dmtf-verdict` reads what the validators wrote instead. The
protocol half is a reading — pass and fail counts out of the `results.json` that
tool always writes. The service half is a discrimination, because that tool
publishes no machine-readable verdict at all: its results file is the best
available evidence that the run reached the end, and the code says so rather than
implying more. Both shapes were taken from the pinned versions by reading them;
`dmtf.py` names the file and line each one came from, and anything that is not
those shapes scores `2` rather than being guessed at.

## Where it sits

```
arbiter-engine        the invariant envelope
bmc-sensor-audit      the referee: declaration diff, liveness, attestation
qa-orchestrator       injects faults, checks the referee caught them
cert-generator        renders the certificate, holds unit identity
DMTF validators       adopted, not built
odm-qa-pipeline       this: the four in order, and one verdict
```

## Licence

Apache-2.0.
