#!/usr/bin/env python3
"""
Eval v6 MiniCheck driver, the local-checker secondary arm (PREREGISTRATION.md section 2.5 and 8.5; plan section 7).

Runs bespoke-minicheck:7b over every CITED pair of the v6 check plan (`checks_plan.jsonl`; pairs whose only reason is
`gold_shown` are skipped), with the same claims, bm25/1 spans and cache as the hosted 0.2.0 checker, and writes
`checks_local.jsonl` (the file evaluate_v6.py passes as --local-checks, with --local-accepted-checker 98751cc0...).

It builds `tools/evidence/support/minicheck_check.MiniCheckChecker` from `minicheck_pin.json` (no edit to either) and calls
`run_checks_v5.run_checks(plan, checker, cache, cache)`. Identity is asserted: checker_id 98751cc07911d57a1586848dfb8c4e7b,
model digest 66607904...7a00, adapter and pin hashes as in the preregistration. A pair already in the cache is not called again.
About 4,700 cited pairs at 1.6 s each, about 2 h of local time, $0. It must not run while collect_v6.py runs.

`--run` is required. Without it the script does only offline work (the checker_id is recomputed from the on-disk files, the
installed model's digest is read from Ollama's manifest file, the plan is counted) and exits 2. Ollama is contacted only with --run.

Usage
  local_checks_v6.py --plan O/checks_plan.jsonl --cache O/evidence-cache --out O/checks_local.jsonl --run
"""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
V6 = Path(__file__).resolve().parent
REPO = V6.parents[1]
SUPPORT = REPO / "tools" / "evidence" / "support"
CHECKER_ID = "98751cc07911d57a1586848dfb8c4e7b"
MODEL_DIGEST = "66607904c165445540331c2f005bb5120edd939008ba1fe1e75151ed827a7a00"
OLLAMA_VERSION = "0.17.7"
# preregistered hashes (prereg 2.5), as prefix / suffix of the sha256
ADAPTER = ("5aacba26", "0a")
PIN = ("efeca684", "f34")
SEC_PER_PAIR = 1.6
MIN_FREE_GB = 10.0


def _load(name, path, sys_path=()):
    if name in sys.modules:
        return sys.modules[name]
    for p in sys_path:
        sys.path.insert(0, str(p))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# minicheck_check imports check / local_check / canonical from tools/evidence and tools/evidence/support
MC = _load("minicheck_check", SUPPORT / "minicheck_check.py", [SUPPORT.parent, SUPPORT])
RC = _load("run_checks_v5", SUPPORT / "run_checks_v5.py")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def model_manifest_digest(tag="bespoke-minicheck:7b"):
    """The digest /api/tags reports is the sha256 of the model's manifest file: read it from disk, no server call."""
    name, _, t = tag.partition(":")
    root = Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama" / "models")
    p = root / "manifests" / "registry.ollama.ai" / "library" / name / (t or "latest")
    return sha(p) if p.exists() else None


def offline_checks(plan_path, cache, out):
    res = []

    def chk(name, ok, detail):
        res.append((name, bool(ok), detail))

    a, pn = sha(SUPPORT / "minicheck_check.py"), sha(SUPPORT / "minicheck_pin.json")
    chk("adapter hash", a.startswith(ADAPTER[0]) and a.endswith(ADAPTER[1]), a[:8] + "..." + a[-2:])
    chk("pin hash", pn.startswith(PIN[0]) and pn.endswith(PIN[1]), pn[:8] + "..." + pn[-3:])
    pin = MC.load_pin()
    chk("pin model digest", pin["model_digest"] == MODEL_DIGEST, pin["model_digest"][:8])
    try:
        c = MC.MiniCheckChecker(pin=pin, verify=False, ollama_version=OLLAMA_VERSION)
        chk("checker_id recomputed offline", c.checker_id == CHECKER_ID, c.checker_id)
    except Exception as e:           # noqa: BLE001
        chk("checker_id recomputed offline", False, repr(e))
    got = model_manifest_digest(pin["model"])
    chk("installed model digest (on-disk manifest)", got == MODEL_DIGEST, (got or "not installed")[:12])
    chk("plan", Path(plan_path).exists(), str(plan_path))
    chk("evidence cache", Path(cache).is_dir(), str(cache))
    chk("out under v6/results", (V6 / "results") in Path(out).resolve().parents, str(out))
    free = shutil.disk_usage(REPO).free / 1e9
    chk("disk", free >= MIN_FREE_GB, f"{free:.1f} GB free")
    return res


def cited_rows(plan):
    return [r for r in plan if "cited" in r["reasons"]]


def main(argv=None):
    ap = argparse.ArgumentParser(description="eval v6 MiniCheck driver (secondary local-checker arm)")
    ap.add_argument("--plan", required=True, help="checks_plan.jsonl of the v6 run")
    ap.add_argument("--cache", required=True, help="evidence cache root (captures and support records)")
    ap.add_argument("--out", required=True, help="checks_local.jsonl")
    ap.add_argument("--workers", type=int, default=1, help="Ollama runs with OLLAMA_NUM_PARALLEL=1; more workers only queue")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--run", action="store_true", help="call Ollama; without it: offline checks and the plan, then refuse")
    a = ap.parse_args(argv)

    res = offline_checks(a.plan, a.cache, a.out)
    plan = RC.read_jsonl(a.plan) if Path(a.plan).exists() else []
    cited = cited_rows(plan)
    if a.limit:
        cited = cited[:a.limit]
    for n, ok, d in res:
        print(f"[{'ok' if ok else 'FAIL'}] {n}: {d}")
    by = Counter("+".join(sorted(r["reasons"])) for r in plan)
    print(json.dumps({"plan_rows": len(plan), "by_reasons": dict(by), "cited_pairs_to_check": len(cited),
                      "estimate_hours": round(len(cited) * SEC_PER_PAIR / 3600, 2), "workers": a.workers,
                      "output": str(a.out)}, indent=1))
    failed = [n for n, ok, _ in res if not ok]
    if not a.run:
        print("REFUSED: pass --run to call Ollama." + (f" Failing checks: {failed}" if failed else " All offline checks pass."))
        return 2
    if failed:
        sys.exit(f"ABORT: offline checks failed: {failed}")
    if subprocess.run(["pgrep", "-f", "collect_v6.py"], capture_output=True).returncode == 0:
        sys.exit("ABORT: collect_v6.py is running; the MiniCheck arm runs after collection, never concurrently")
    checker = MC.MiniCheckChecker(pin=MC.load_pin(), verify=True)        # contacts Ollama: /api/tags digest, /api/version
    if checker.checker_id != CHECKER_ID:
        sys.exit(f"ABORT: checker_id {checker.checker_id} != {CHECKER_ID}")
    if checker.model_digest != "sha256:" + MODEL_DIGEST:
        sys.exit(f"ABORT: model digest {checker.model_digest} != {MODEL_DIGEST}")
    if checker.ollama_version != OLLAMA_VERSION:
        sys.exit(f"ABORT: Ollama {checker.ollama_version}, pinned {OLLAMA_VERSION}")
    log = str(Path(a.out).with_name("check_calls_local.jsonl"))
    rows, _, wall = RC.run_checks(cited, checker, a.cache, a.cache, a.workers, a.retries, None, log)
    bad = [r["check_key"] for r in rows if r["checker"]["checker_id"] != CHECKER_ID]
    if bad:
        sys.exit(f"ABORT: {len(bad)} rows carry another checker_id")
    RC.write_jsonl(str(a.out), rows)
    st = Counter(r["status"] for r in rows)
    lab = Counter((r["label"] or "-") for r in rows if r["status"] == "ok")
    print(json.dumps({"checker_id": CHECKER_ID, "planned": len(cited), "written": len(rows), "status": dict(st),
                      "labels": dict(lab), "wall_s": round(wall, 1)}, indent=1))
    return 0 if len(rows) == len(cited) else 2


if __name__ == "__main__":
    sys.exit(main())
