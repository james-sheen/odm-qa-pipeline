#!/usr/bin/env python3
"""Resolve this manifest's pins at every release each one claims.

A version range is a claim about every release inside it. This package publishes
seven of them in `pins.json`, and the composition job exercises exactly one point
in that space -- whatever the resolver picks, which is the newest of each and the
release each claim is least likely to be wrong about.

WHAT THIS PACKAGE'S RANGES ACTUALLY FAIL AT, measured from its own history rather
than assumed: not a component breaking on its own, but two pins that cannot both
hold. `odm-cert-generator` 0.2.2 requires the referee at `>=0.3.0` while this
manifest still said `<0.3`, and pip resolved that by quietly giving the
certificate gate a version the manifest does not admit. Nothing went red. So the
question this probe asks per release is the question that has actually gone
wrong: with THIS component pinned to THIS version, does the whole manifest still
resolve, and does every other component land inside its own declared range?

    python3 tools/probe_pin.py                     # every component
    python3 tools/probe_pin.py --only arbiter-engine
    python3 tools/probe_pin.py --sweep             # keep walking below each floor
    python3 tools/probe_pin.py --keep

**IT IS SLOW AND IT IS NOT A BLOCKING JOB.** Thirty-two in-range releases today,
each a real environment with every gate's requirements in it. Run it after
anything this manifest names is released, and before moving a floor or a ceiling.

Exit 0 every in-range release resolves and every other pin holds beside it, 1 a
declared claim is false, 2 the probe could not run -- INCLUDING when a range
holds no releases at all. *Every release passed* is true of an empty set and
means nothing, so an empty range is a failure to measure and not a pass.

WHAT RESOLUTION CAN AND CANNOT DEMONSTRATE, stated because the two ends of a
range are not symmetric here. A CEILING that is wrong shows up: a component whose
own requirements drag a sibling outside the range this manifest admits is exactly
the defect above, and the resolved versions are read back and compared to catch
it. A FLOOR usually does not, because a component below the floor still resolves
-- what the floor records is behaviour, and the gate commands are what would show
it. So `floor-not-demonstrated` is the ordinary answer here rather than a gap in
the run, and the number in the manifest comes from the `role` note beside it.

WHAT THIS DOES NOT DECIDE: whether a passing below-floor release means the floor
should drop. The pin is true either way; `floor-not-demonstrated` says only that
this probe is not where the number came from.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "src" / "odm_qa_pipeline" / "pins.json"
EVIDENCE = pathlib.Path(__file__).resolve().parent / "pin_evidence.json"

RANGE = re.compile(r">=\s*([0-9][^,]*)\s*,\s*<\s*([0-9][^\s\"']*)")


def _key(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", text))


def declared_pins() -> dict[str, dict]:
    """Read the ranges out of `pins.json`, never from a list written here.

    A list here would be a second record of the manifest and would go on
    reporting the old range after somebody edited the real one -- which is the
    shape of failure a pin probe exists to catch, reproduced inside the probe.
    """
    components = json.loads(MANIFEST.read_text())["components"]
    found: dict[str, dict] = {}
    for name, spec in components.items():
        requirement = spec["requirement"]
        bounds = RANGE.search(requirement)
        if not bounds:
            continue
        found[name] = {"requirement": requirement,
                       "low": bounds.group(1).strip(),
                       "high": bounds.group(2).strip()}
    return found


def released(dist: str) -> list[str]:
    """Every non-yanked, non-prerelease version PyPI serves for `dist`."""
    with urllib.request.urlopen(
            f"https://pypi.org/pypi/{dist}/json", timeout=60) as response:
        payload = json.load(response)
    out = []
    for version, files in (payload.get("releases") or {}).items():
        if not files or all(f.get("yanked") for f in files):
            continue
        if re.search(r"[a-zA-Z]", version):          # a, b, rc, dev
            continue
        out.append(version)
    return sorted(out, key=_key)


def split(versions: list[str], low: str, high: str) -> tuple[list[str], list[str]]:
    in_range = [v for v in versions if _key(low) <= _key(v) < _key(high)]
    if not in_range:
        return [], []
    beneath = [v for v in versions if _key(v) < _key(in_range[0])]
    return in_range, beneath


def requirements(pins: dict[str, dict], forced: str, version: str) -> list[str]:
    """The manifest's whole requirement set, with one component pinned exactly.

    Every other component keeps its declared range, because the question is
    whether the SET holds -- pinning the others as well would ask whether one
    hand-chosen point holds, which is what the composition job already answers.
    """
    out = []
    for name, spec in pins.items():
        if name == forced:
            # The extras survive the pin: `bmc-sensor-audit[detect]` without its
            # extra is a different install, and the manifest names the extra.
            head = spec["requirement"].split(">=")[0].strip()
            out.append(f"{head}=={version}")
        else:
            out.append(spec["requirement"])
    return out


def exercise(pins: dict, dist: str, version: str, home: pathlib.Path) -> tuple[bool, str]:
    """Install the whole manifest with one component pinned, then check the rest."""
    made = subprocess.run([sys.executable, "-m", "virtualenv", "-q", str(home)],
                          capture_output=True, text=True)
    if made.returncode != 0:
        return False, f"could not create an environment: {made.stderr.strip()[:120]}"
    pip, python = home / "bin" / "pip", home / "bin" / "python"
    wanted = requirements(pins, dist, version)
    install = subprocess.run(
        [str(pip), "install", "-q", "--no-cache-dir", *wanted],
        capture_output=True, text=True)
    if install.returncode != 0:
        tail = (install.stderr or install.stdout).strip().splitlines()
        return False, f"did not resolve: {tail[-1][:160] if tail else '?'}"

    # THE HALF THE RESOLVER DOES NOT ANSWER. An install that succeeds says the
    # set is satisfiable; it does not say every component landed where this
    # manifest claims. That is the exact defect this package already shipped --
    # a gate quietly given a version the manifest does not admit -- and it is
    # invisible unless the resolved versions are read back and compared.
    names = {n.split("[")[0].strip(): n for n in pins}
    probe = subprocess.run(
        [str(python), "-c",
         "import json,importlib.metadata as m;"
         f"print(json.dumps({{n: m.version(n) for n in {sorted(names)!r}}}))"],
        capture_output=True, text=True, cwd=str(home))
    try:
        resolved = json.loads(probe.stdout)
    except Exception:
        tail = probe.stderr.strip().splitlines()
        return False, f"could not read back what was installed: {tail[-1][:140] if tail else '?'}"

    # THE FORCED COMPONENT IS EXEMPT FROM ITS OWN RANGE, and leaving it in made
    # the below-floor leg tautological: pinning 0.3.1 under a floor of 0.3.2 and
    # then reporting *0.3.1 is outside 0.3.2* restates the instruction as a
    # finding. Every other component is checked, which is where a real answer
    # lives -- the historical defect was a gate quietly given a version this
    # manifest does not admit, and that shows up on the OTHERS.
    strayed = []
    for name, got in sorted(resolved.items()):
        if names[name] == dist:
            continue
        spec = pins[names[name]]
        if not (_key(spec["low"]) <= _key(got) < _key(spec["high"])):
            strayed.append(f"{name} {got} outside {spec['low']},{spec['high']}")
    if strayed:
        return False, "resolved outside the manifest: " + "; ".join(strayed)
    return True, ", ".join(f"{n} {v}" for n, v in sorted(resolved.items()))


def probe_one(pins: dict, name: str, sweep: bool, keep: bool) -> dict:
    spec = pins[name]
    dist = spec["requirement"].split("[")[0].split(">")[0].strip()
    versions = released(dist)
    in_range, beneath = split(versions, spec["low"], spec["high"])
    print(f"\n{spec['requirement']}")
    print(f"  in range : {', '.join(in_range) or '(none)'}")
    print(f"  below    : {', '.join(reversed(beneath)) or '(nothing released below)'}")
    if len(in_range) == 1:
        print("  note     : the range holds one release today, so *every release "
              "in range* is a claim about one")
    result = {"component": name, "specifier": f"{spec['low']},{spec['high']}",
              "in_range": in_range, "below": [], "failures": []}
    if not in_range:
        result["verdict"] = "empty-range"
        return result

    work = pathlib.Path(tempfile.mkdtemp(prefix="oqp-pin-"))
    try:
        for version in in_range:
            ok, note = exercise(pins, name, version, work / f"in-{version}")
            print(f"  in  {version}: {'pass' if ok else 'FAIL'} -- {note[:120]}")
            if not ok:
                result["failures"].append(version)
        walked = list(reversed(beneath)) if sweep else beneath[-1:]
        demonstrated = False
        for version in walked:
            ok, note = exercise(pins, name, version, work / f"under-{version}")
            print(f"  under {version}: {'pass' if ok else 'fail'} -- {note[:120]}")
            result["below"].append({"version": version, "passed": ok})
            if not ok:
                demonstrated = True
                break
        passed_below = [r["version"] for r in result["below"] if r["passed"]]
        if result["failures"]:
            result["verdict"] = "claim-false"
        elif demonstrated and not passed_below:
            result["verdict"] = "floor-holds"
        elif demonstrated:
            result["verdict"] = "floor-higher-than-measured"
        else:
            result["verdict"] = "floor-not-demonstrated"
        result["passed_below"] = passed_below
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", action="append", default=None,
                    help="probe just this component; repeatable")
    ap.add_argument("--sweep", action="store_true",
                    help="keep walking below the floor until something fails")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--out", type=pathlib.Path, default=EVIDENCE)
    args = ap.parse_args(argv)

    pins = declared_pins()
    if not pins:
        print("could-not-run: the manifest declares no bounded range, so there "
              "is nothing to exercise. An empty sweep reports the same as a "
              "clean one and means something else entirely", file=sys.stderr)
        return 2
    chosen = sorted(args.only) if args.only else sorted(pins)
    unknown = [n for n in chosen if n not in pins]
    if unknown:
        print(f"could-not-run: no such component in the manifest: {unknown}",
              file=sys.stderr)
        return 2

    results = []
    for name in chosen:
        try:
            results.append(probe_one(pins, name, args.sweep, args.keep))
        except (urllib.error.URLError, TimeoutError) as problem:
            print(f"could-not-run: PyPI is not reachable for {name}: {problem}",
                  file=sys.stderr)
            return 2

    empty = [r["component"] for r in results if r["verdict"] == "empty-range"]
    false = [r for r in results if r["verdict"] == "claim-false"]
    print(f"\n{len(results)} range(s) probed, "
          f"{sum(len(r['in_range']) for r in results)} in-range release(s) resolved")
    for r in results:
        if r["verdict"] == "floor-holds":
            print(f"  note: {r['component']}: the floor holds -- "
                  f"{r['below'][-1]['version']} is the release immediately below "
                  f"it and it fails")
        elif r["verdict"] == "floor-higher-than-measured":
            print(f"  note: {r['component']}: FLOOR HIGHER THAN MEASURED -- "
                  f"{', '.join(r['passed_below'])} also resolve. The pin is still "
                  f"true; whether the floor should drop is a decision, and this "
                  f"probe reaches only as far as resolution")
        elif r["verdict"] == "floor-not-demonstrated":
            print(f"  note: {r['component']}: FLOOR NOT DEMONSTRATED -- every "
                  f"release tried below it also resolves. Re-run with --sweep")
    code = 2 if empty else 1 if false else 0
    if empty:
        print(f"  could-not-run: {', '.join(empty)} -- the range holds no "
              f"releases, and *every release passed* is true of an empty set")
    partial = sorted(set(pins) - set(chosen))
    args.out.write_text(json.dumps(
        {"ranges": results, "exit": code, "swept": args.sweep,
         # NAMED, because a file that records five of seven ranges and says
         # nothing about the other two reads as a manifest that was exercised.
         "not_probed_this_run": partial}, indent=1) + "\n")
    if partial:
        print(f"  NOT probed this run: {', '.join(partial)}")
    print(f"  evidence: {args.out}")
    print(f"EXIT={code}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
