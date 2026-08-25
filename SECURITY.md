# Security

## Report privately

**Use GitHub's private vulnerability reporting** — the *Security* tab on this
repository, *Report a vulnerability*. That opens a channel visible only to the
maintainer.

**Do not open a public issue for anything in the list below.** Some of these are
cases where *the report itself is the disclosure*: an issue quoting what a
pipeline run put in a job log may publish the thing that should not have been
logged.

If private reporting is unavailable to you, open a public issue saying only
**that** you have something to report and nothing about what it is.

## What counts as a security issue here

This package composes four gates as subprocesses and aggregates one verdict. It
has **no runtime dependencies and imports none of the tools it runs**, which
bounds the surface but does not empty it.

**1. It ships CI templates, and templates are executable.** The templates under
`templates/` are copied into other people's pipelines.

- **Any interpolation of an untrusted value into a shell line** is a security
  issue. Inputs reach the shell through `env:` precisely so a target URL
  containing a backtick is data rather than code, and
  `tests/test_templates.py::TestNoScriptInjection` exists to keep it that way.
- **Any template step that puts a BMC credential where a job log can reach it**
  is a security issue.

**2. The verdict must not be able to say more than the gates did.** The one thing
this package reports that nothing else can is *the gate that never ran*.

- **Any way to make `aggregate` report a pass when a gate did not report** is a
  security issue, not a defect. A pipeline whose injection step was commented out
  weeks ago and has been green ever since is the exact failure this exists to
  prevent.
- **A gate result accepted from a file the pipeline did not produce**, or an exit
  code outside `{0,1,2}` read as success rather than as incomplete, is the same
  class.

**3. It publishes version constraints.** `pins.json` is what a reader installs
from.

- **A floor naming a version that cannot do what the manifest says it can** is a
  security issue when the capability is a security one, because a reader pinning
  down for reproducibility gets a tool that cannot do its job on the manifest's
  word that it can.

## What does not need private handling

Ordinary defects, template lint, aggregation arithmetic, crashes on malformed
result files, and a gate reporting `2` because a tool it needs is not installed —
that is the design: a gate that could not run has not passed, and says so.

## What to expect

A single maintainer, no service-level commitment, and no bounty. You will get an
acknowledgement and an honest answer about whether and when it will be fixed —
including *not soon*, when that is true.

**The supported version is the latest release on PyPI** and nothing older. A fix
lands on the default branch and ships in the next release; the reply will say
which. No version literal appears in this file on purpose — a number here is a
number that goes stale.

## Scope

This repository only. Vulnerabilities in the tools this pipeline runs belong to
those projects: `bmc-sensor-audit`, `qa-orchestrator`, `odm-cert-generator`,
`arbiter-engine`, and DMTF's validators each have their own repository. A flaw in
a BMC or in vendor firmware belongs to that vendor.
