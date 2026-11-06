#!/usr/bin/env python3
"""
Eval v6 post-collection driver: the frozen v5 driver (post_collect_v5.py, loaded by path, never edited), pointed at
real-agent-eval/v6/results/conf (PREREGISTRATION.md section 11).

Overrides: OUT -> v6/results/conf; step_checks (the four run_checks_v5.py calls now carry --out, --cache and --raw-dir
for the v6 directory, because run_checks_v5 defaults to v5's). Every other step (inputs, judges, regen, loao, local, rows)
derives its paths from OUT and is v5's code. The pinned-CLI check and the 1,100-record check are kept.

The v6 check cache (v6/results/conf/evidence-cache) and the CB-S store (judge-store-cbs) must be the APFS clones of v5's
(plan section 3); `checks` and `judges` refuse to start if the clones are missing. The J and RS stores start empty.

`--run` is required: without it the script prints the commands it would issue and exits 2, because `checks`, `judges`,
`regen`, `loao` and `rows` make hosted calls (pinned claude CLI, hosted checker 0.2.0; plan estimate about $43, cap $60).

Usage
  post_collect_v6.py --steps seed --run                # plan section 3: clone v5's evidence cache and CB-S store (opt-in step)
  post_collect_v6.py --steps checks,inputs,judges,regen,loao,rows --run
  post_collect_v6.py --steps local,rows --run          # optional exploratory J_local (mistral, a non-participant)
  post_collect_v6.py --steps checks,judges             # dry run
"""
import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
V6 = Path(__file__).resolve().parent
V5 = V6.parent / "v5"
ROOT = V6.parents[1]

_spec = importlib.util.spec_from_file_location("post_collect_v5", V5 / "post_collect_v5.py")
P = importlib.util.module_from_spec(_spec)
sys.modules["post_collect_v5"] = P
_spec.loader.exec_module(P)               # imports the frozen evaluate_v5 through its own sys.path entry
E = P.E

OUT = V6 / "results" / "conf"
CACHE = OUT / "evidence-cache"
P.OUT = OUT
MAX_USD = "60"                           # prereg section 8.8 cap; the central estimate is about $43
HOSTED = {"checks", "judges", "regen", "loao", "rows"}
NO_FILE_READS = {"checks", "judges", "local", "seed"}     # steps that only issue commands (safe to print in a dry run)


def step_checks():
    """v5's four run_checks_v5.py calls, each pointed at the v6 directory and cache."""
    rc = [P.VENV_PY, ROOT / "tools/evidence/support/run_checks_v5.py"]
    a = ["--split", "conf", "--out", OUT, "--cache", CACHE, "--raw-dir", OUT / "raw"]
    P.sh(rc + ["captures"] + a, OUT / "captures.log")
    P.sh(rc + ["plan"] + a + ["--gold-scope", "decisive", "--gold-restrict", "fever,scifact"], OUT / "plan.log")
    P.sh(rc + ["--claude-bin", P.CLAUDE, "check"] + a + ["--workers", "6", "--retries", "2", "--max-usd", MAX_USD,
                                                         "--expect-checker", E.PREREG_CHECKER], OUT / "checks_run.log")
    P.sh(rc + ["gold-avail"] + a, OUT / "gold_avail.log")


P.step_checks = step_checks

V5_CONF = V5 / "results" / "conf"
SEEDS = [(V5_CONF / "evidence-cache", CACHE), (V5_CONF / "judge-store-cbs", OUT / "judge-store-cbs")]


def step_seed():
    """Plan section 3 (prereg 5, 8.3): APFS-clone v5's evidence cache and CB-S store into the v6 directory. v5's copies are only
    read. Refuses to overwrite an existing target. The J and RS stores are not seeded (their prompts contain the new answers)."""
    OUT.mkdir(parents=True, exist_ok=True)
    for src, dst in SEEDS:
        if not src.exists():
            raise SystemExit(f"ABORT: {src} is missing")
        if dst.exists():
            raise SystemExit(f"ABORT: {dst} already exists; not overwriting")
        P.sh(["/bin/cp", "-Rc", src, dst])
        n = sum(1 for f in dst.rglob("*") if f.is_file())
        print(f"seeded {dst.name}: {n} files (record in v6/FREEZE.json)", file=sys.stderr)


def preflight(steps):
    """Local checks before any hosted step: the clones exist, the pinned CLI binary exists."""
    if HOSTED & set(steps):
        if not P.CLAUDE.exists():
            raise SystemExit(f"ABORT: pinned CLI {P.CLAUDE} is missing (plan section 0)")
    if {"checks", "judges"} & set(steps):
        for d, why in ((CACHE, "evidence cache"), (OUT / "judge-store-cbs", "CB-S store")):
            if not d.exists():
                raise SystemExit(f"ABORT: {d} is missing; clone v5's {why} first (plan section 3: /bin/cp -Rc)")


def main(argv=None):
    global MAX_USD
    ap = argparse.ArgumentParser(description="eval v6 post-collection driver")
    ap.add_argument("--steps", default=",".join(P.STEPS))
    ap.add_argument("--run", action="store_true", help="execute (hosted calls); without it: print the plan and refuse")
    ap.add_argument("--max-usd", default=MAX_USD)
    a = ap.parse_args(argv)
    MAX_USD = a.max_usd
    steps = a.steps.split(",")
    bad = [s for s in steps if s not in P.STEPS + ["seed"]]
    if bad:
        raise SystemExit(f"ABORT: unknown steps {bad}; valid: {['seed'] + P.STEPS} (seed is opt-in and not in the default list)")
    if not a.run:
        print("DRY RUN (no --run): no command is executed and no hosted call is made.")
        print(f"OUT = {OUT}\nsteps = {steps}; hosted steps among them: {sorted(HOSTED & set(steps))}; --max-usd {MAX_USD}")
        P.sh = lambda argv_, log=None: print("+ " + " ".join(map(str, argv_)) + (f"  > {log}" if log else ""))
        for s in steps:
            print(f"== {s}")
            if s in NO_FILE_READS:
                if s == "seed":
                    for a_, b_ in SEEDS:
                        P.sh(["/bin/cp", "-Rc", a_, b_])
                else:
                    (step_checks if s == "checks" else getattr(P, "step_" + s))()
            else:
                print("   (reads files under OUT; commands are printed when run)")
        print("REFUSED: pass --run to execute.")
        return 2
    preflight(steps)
    v = subprocess.run([str(P.CLAUDE), "--version"], capture_output=True, text=True,
                       env=dict(os.environ, DISABLE_AUTOUPDATER="1")).stdout
    if not v.startswith(P.CLI_PIN + " "):
        raise SystemExit(f"ABORT: pinned CLI {P.CLAUDE} reports {v!r}")
    n = len(list((OUT / "raw").glob("*.json")))
    if n != P.N_ITEMS:
        raise SystemExit(f"ABORT: {n} raw records in {OUT / 'raw'}, expected {P.N_ITEMS} (collection incomplete)")
    fns = {s: (step_seed if s == "seed" else getattr(P, "step_" + s)) for s in P.STEPS + ["seed"]}
    for s in steps:
        print(f"== {s}", file=sys.stderr, flush=True)
        fns[s]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
