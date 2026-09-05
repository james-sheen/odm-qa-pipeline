# odm-qa-pipeline

Four QA gates, in order, and one verdict from them.

**Released — 0.2.0**, tagged `v0.2.0`, Apache-2.0, on PyPI as `odm-qa-pipeline`.

**0.2.0 raises three floors in `pins.json` to the 0.2.0 releases of the tools
this pipeline runs**: the referee, the injector and the certificate renderer.
`arbiter-engine` stays at `>=0.1.8,<0.2` — it did not break and its ceiling is
still correct. The floors moved because the referee's 0.2.0 refuses a command
that asks to verify and not to verify at once, and a pipeline whose manifest
pinned below that would be handing a reader a tool that cannot do the job the
manifest says it does.

This package was published **last**, after all three were on the index. The
manifest ships inside this wheel and asks no network questions, so nothing here
could have caught a floor naming a version that did not exist yet.

0.1.3 makes the Jenkins template do what 0.1.2's own page says this package
does. The one-capture fix landed in the GitHub workflow only: the Jenkinsfile
went on walking the machine once for `detect` and again for `coverage`, so gate
4 still combined two observations taken moments apart, and the certificate it
rendered named no capture at all. The test class asserting the two templates
match pinned four structural properties and not that one. Both templates are now
asserted against the same invocations, so a fix to one of them cannot pass while
the other keeps the bug.

0.1.2 made the coverage gate take one capture and judge it twice, and corrected
the `arbiter-engine` floor, which had been wrong by two releases. Every
component its manifest names was published before this was.

```
pip install odm-qa-pipeline

odm-qa-pipeline gates            # what runs, and what a failure in each means
odm-qa-pipeline pins             # every version constraint, from one file
odm-qa-pipeline scenarios <dir>  # run whatever scenarios a checkout ships
odm-qa-pipeline aggregate --results qa-results
```

`scenarios` takes a checkout, not a path to a file. It finds scenarios by the
format marker they carry and runs the ones this build can name, so a canary here
does not have to know where another repository keeps them — and a checkout that
offers nothing runnable exits `2`, because a canary that silently checked nothing
is worse than none.

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

### The gate set is closed, and that is the design

`record --gate <name>` refuses a name this package does not declare. It is worth
saying why, because a caller who has written a fifth gate meets the refusal
before any explanation.

`aggregate` exists to report **the gate that never ran** -- the failure this
whole package is for, a pipeline whose injection step was commented out weeks ago
and has been green ever since. It can only do that because it knows which gates
were expected. A name it has never heard of is indistinguishable from a typo in
one it has, so accepting arbitrary names would trade the one thing here that
nothing else can report for a convenience.

The four also run in an order where each answers a question the next assumes, so
a new gate needs a position and a declared question. **Adding one is a change to
this package**, not a string a caller invents. If you have written a gate worth
running, that is an issue worth opening.

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

## Every component is pinned to a version

As of 0.1.1 nothing here tracks a branch. **A branch is not a pin**: the same
pipeline definition can resolve to different code on two consecutive days and
nothing would report a difference, so the manifest carried that state explicitly
while it was true — a `why_unpinned` reason per component, refused by a test if
missing, and printed on every `aggregate` run rather than left in a file nobody
opens. The mechanism stays; it currently has nothing to say.

**One name is not what you would guess.** The certificate gate installs
`odm-cert-generator` and runs a command called `cert-generator`. PyPI
ultranormalises a distribution name by stripping its separators, so
`cert-generator` collides with an unrelated `certgenerator` and is refused. Ask
`odm-qa-pipeline pins --gate certificate` rather than typing it.

**A floor is derived, not chosen, and this manifest got one wrong.** It declared
`arbiter-engine>=0.1.6` until 2026-08-24. Measured by running the referee's own
Stage 2 canary against every release that range admitted: **0.1.6 fails eleven of
its assertions and 0.1.7 fails two.** Nothing broke in practice, because a
resolver picks the newest release either way — but a reader pinning down for
reproducibility would have got a referee that could not do its job, on this
manifest's word that it could. A pin is only ever exercised at one point of its
own range, which is why the floor is the least-tested claim a project makes.

**Publish order matters.** This manifest ships *inside* the wheel, so a floor
naming a version that is not on the index yet is false for as long as that is
true — and nothing here can check it, because that is a network question this
file deliberately asks none of. Publish every component a floor names before
publishing this package. Version 0.1.0 shipped a manifest that was correct for
ten minutes and cost a second release.

## The coverage gate takes ONE capture and judges it twice

It used to walk the machine twice — `detect --target`, then `coverage --target` —
so the attestation and the coverage handed to the certificate gate came from two
different observations taken at two different moments, and the certificate
combined them without saying so. It also asked a BMC under test to serve its whole
sensor tree twice for one gate.

The template now captures once, validates the file, and judges that file:

```
bmc-sensor-audit capture --target ... --out walk.json --print-digest
bmc-sensor-audit validate-walk walk.json --require-complete
bmc-sensor-audit detect   --config ... --walk walk.json --attest-out attestation.json
bmc-sensor-audit coverage --config ... --walk walk.json --json > coverage.json
```

**Judging the file rather than the run is the point of the middle line.**
`capture` exits `2` both when it could not reach the machine and when it reached
the machine and one subtree answered with an error — and the second is a walk the
tool writes on purpose, because knowing which subtree failed is the evidence.
This gate needs a whole one, so it asks for that explicitly rather than inferring
it from an exit code that means two things.

The certificate gate is then handed the same `walk.json`, so the document records
the handle of the exact file both verdicts came from and a recipient can match it
with `sha256sum`.

**`${PIPESTATUS[0]}`, not `$?`.** The capture is piped through `tee` to keep its
printed handle in the artifacts, and after a pipe `$?` is `tee`'s — which succeeds
whatever the capture did.

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
