"""Re-run the frozen second-pool evaluator (`evaluate_v6.py`) on the published artifact.

`evaluate_v6.py` checks every hash in `v6/FREEZE.json` before it runs. A few of the files it lists are
first-pool documents that were redacted for publication (`FROZEN_REDACTIONS.md`), so the check stops
on them. This wrapper replaces only that check: a listed file passes if its hash is the frozen one,
or if `FROZEN_REDACTIONS.md` records exactly that (frozen hash, published hash) pair for that path.
Every other check, and the evaluator itself, run unchanged.

Usage: python3 real-agent-eval/v6/reanalyze_v6.py <the evaluate_v6.py arguments>
"""
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

V6 = Path(__file__).resolve().parent
ROOT = V6.parents[1]


def documented_redactions():
    """{path: (frozen sha256, published sha256)} from the tables in FROZEN_REDACTIONS.md."""
    row = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*`([0-9a-f]{64})`\s*\|\s*`([0-9a-f]{64})`\s*\|", re.M)
    return {p: (a, b) for p, a, b in row.findall((ROOT / "FROZEN_REDACTIONS.md").read_text())}


def verify_v6_freeze(need_frozen=True):
    d = json.loads((V6 / "FREEZE.json").read_text())
    if need_frozen and (d.get("status") != "FROZEN" or d.get("pending")):
        raise SystemExit("ABORT: v6/FREEZE.json is not FROZEN with nothing pending")
    red = documented_redactions()
    bad, redacted = [], []
    for p, h in sorted(d.get("sha256", {}).items()):
        f = ROOT / p
        got = hashlib.sha256(f.read_bytes()).hexdigest() if f.exists() else None
        if got == h:
            continue
        if red.get(p) == (h, got):
            redacted.append(p)
        else:
            bad.append(p)
    if bad:
        raise SystemExit(f"ABORT: v6/FREEZE.json hash mismatch not explained by FROZEN_REDACTIONS.md: {bad}")
    print(f"v6/FREEZE.json: {len(d['sha256'])} hashes checked; documented redactions accepted: {redacted}",
          file=sys.stderr)
    return d


def main():
    spec = importlib.util.spec_from_file_location("evaluate_v6", V6 / "evaluate_v6.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["evaluate_v6"] = mod
    spec.loader.exec_module(mod)
    mod.verify_v6_freeze = verify_v6_freeze
    return mod.main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
