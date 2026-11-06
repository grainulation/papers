#!/usr/bin/env python3
"""
Eval v6 collector: the frozen v5 collector (collect_v5.py, loaded by path, never edited) with the v6 pool.

Overrides constants only (PREREGISTRATION.md section 11):
  MODELS         the v6 pool, in v5's list positions (section 4.1)
  V3_MANIFEST    -> v6/pool_manifest.json  ({"model_digests": {tag: {"digest": ..}}}, same shape as v3's)
  FREEZE         -> v6/FREEZE.json
  CONF_FROZEN    += collect_v6.py, pool_manifest.json, PREREGISTRATION.md
The prompts, schemas, items, retrieval and dispatch code are v5's, byte for byte (they resolve from v5's HERE).

Additions (all outside the collection loop):
  * --out is mandatory and must be under real-agent-eval/v6/results/ (v5's raw records are never touched);
  * --run is required to collect. Without it the script runs the start-up checks, prints the dispatch plan and
    exits 2 ("refused"). The checks and the plan never call Ollama (digests are read from Ollama's on-disk manifests);
  * conf also refuses while v6/FREEZE.json is missing, not FROZEN, or has a non-empty `pending`;
  * the embedder digest is checked against pool_manifest.json (it must still be v5's 0a109f422b47...);
  * no --mixed-fleet arm in v6, and `build-dense` is refused (v6 reuses v5's dense index).
`audit` and `judge-inputs` read raw records only (no Ollama) and run without --run, but --out must still be under v6/results/.

Usage (plan sections 4, 6, 7)
  collect_v6.py --split dev --out real-agent-eval/v6/results/dev --run
  collect_v6.py --split conf --n-items 1100 --out real-agent-eval/v6/results/conf --run
  collect_v6.py audit --out real-agent-eval/v6/results/dev
  collect_v6.py --split dev --out real-agent-eval/v6/results/dev          # dry run: checks + plan, then refuses
"""
import argparse
import hashlib
import importlib.util
import json
import os
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
V6 = Path(__file__).resolve().parent
V5 = V6.parent / "v5"
REPO = V6.parents[1]
MODELS_V6 = ["falcon3:3b", "olmo2:7b", "exaone3.5:7.8b", "nemotron-mini:4b", "granite3.3:2b"]   # v5 list positions
EMBED_TAG = "nomic-embed-text:latest"
EMBED_DIGEST_V5_PREFIX = "0a109f422b47"
OLLAMA_VERSION = "0.17.7"
MIN_FREE_GB = 10.0

_spec = importlib.util.spec_from_file_location("collect_v5", V5 / "collect_v5.py")
C = importlib.util.module_from_spec(_spec)
sys.modules["collect_v5"] = C
_spec.loader.exec_module(C)

C.MODELS = MODELS_V6
C.V3_MANIFEST = V6 / "pool_manifest.json"
C.FREEZE = V6 / "FREEZE.json"
C.CONF_FROZEN = C.CONF_FROZEN + ["real-agent-eval/v6/collect_v6.py", "real-agent-eval/v6/pool_manifest.json",
                                 "real-agent-eval/v6/PREREGISTRATION.md"]


# ── checks (each returns (ok, detail); none calls Ollama unless `live`) ─────────

def ollama_models_dir():
    return Path(os.environ.get("OLLAMA_MODELS") or (Path.home() / ".ollama" / "models"))


def local_manifest_digest(tag):
    """Ollama's /api/tags digest is the sha256 of the model's manifest file; read it from disk, no server call."""
    name, _, t = tag.partition(":")
    p = ollama_models_dir() / "manifests" / "registry.ollama.ai" / "library" / name / (t or "latest")
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def read_pool_manifest():
    p = C.V3_MANIFEST
    if not p.exists():
        return None, f"{p.relative_to(REPO)} does not exist (plan section 1: pull the pool and write it)"
    m = json.loads(p.read_text())
    d = m.get("model_digests", {})
    missing = [t for t in MODELS_V6 + [EMBED_TAG] if not (d.get(t) or {}).get("digest")]
    if missing:
        return None, f"pool_manifest.json lacks digests for {missing}"
    return m, "ok"


def check_pool_manifest():
    m, msg = read_pool_manifest()
    if m is None:
        return False, msg
    d = m["model_digests"]
    if not d[EMBED_TAG]["digest"].startswith(EMBED_DIGEST_V5_PREFIX):
        return False, f"embedder digest {d[EMBED_TAG]['digest'][:12]} is not v5's {EMBED_DIGEST_V5_PREFIX}"
    return True, f"{len(MODELS_V6)} agents + embedder; manifest sha256 {C.sha256_file(C.V3_MANIFEST)[:16]}"


def check_digests_offline():
    m, msg = read_pool_manifest()
    if m is None:
        return False, msg
    bad = []
    for t in MODELS_V6 + [EMBED_TAG]:
        got = local_manifest_digest(t)
        if got != m["model_digests"][t]["digest"]:
            bad.append((t, (got or "not installed")[:12], m["model_digests"][t]["digest"][:12]))
    return (not bad, f"mismatch (installed vs manifest): {bad}" if bad else "5 agents + embedder equal pool_manifest.json (on-disk manifests)")


def check_freeze(split):
    f = C.FREEZE
    if not f.exists():
        return (split != "conf"), ("no v6/FREEZE.json (allowed for dev, before the freeze)" if split != "conf"
                                   else "conf needs v6/FREEZE.json (prereg section 15 not complete)")
    d = json.loads(f.read_text())
    if split == "conf":
        if d.get("status") != "FROZEN":
            return False, f"v6/FREEZE.json status is {d.get('status')!r}"
        if d.get("pending"):
            return False, f"v6/FREEZE.json pending is not empty: {d['pending']}"
    try:
        C.verify_freeze(split)          # hash of every listed file; conf also needs CONF_FROZEN listed
    except SystemExit as e:
        return False, str(e)
    return True, f"{len(d.get('sha256', {}))} hashes verified"


def check_corpus(split, n_items=None):
    """Corpus and index hashes, the dense manifest. Loads the local indexes; embeds nothing (no Ollama)."""
    try:
        items = load_items(split)
        corpora = {x["corpus"] for x in items}
        need_dense = "scifact" in corpora and any(a == "dense" for x in items for a in C.retriever_assignment(C.agent_view(x)).values())
        C.Retrieval(corpora, need_dense, verify_index=True)
    except SystemExit as e:
        return False, str(e)
    return True, f"corpora {sorted(corpora)} index hashes = corpus_manifest.json; dense manifest verified={need_dense}"


def check_disk():
    free = shutil.disk_usage(REPO).free / 1e9
    return free >= MIN_FREE_GB, f"{free:.1f} GB free (minimum {MIN_FREE_GB:.0f})"


def check_live():
    """Run mode only: the server version and the digests as the server reports them (this contacts Ollama)."""
    v = C.http_json("/api/version", timeout=5).get("version")
    if v != OLLAMA_VERSION:
        return False, f"Ollama {v}, v5 pin is {OLLAMA_VERSION}"
    return True, f"Ollama {v}"


def load_items(split):
    items = sorted((json.loads(l) for l in open(V5 / C.SPLIT_FILES[split])), key=lambda x: x["order"])
    assert [x["order"] for x in items] == list(range(len(items)))
    return items


# ── dispatch plan (same code path as C.cmd_collect, no calls) ──────────────────

def dispatch_orders(items):
    rng = random.Random(C.DISPATCH_SEED)
    orders = {}
    for x in items:
        o = list(MODELS_V6)
        rng.shuffle(o)
        orders[x["id"]] = o
    return orders


def plan(args):
    all_items = load_items(args.split)
    orders = dispatch_orders(all_items)
    items = all_items[:args.n_items] if args.n_items is not None else all_items
    if args.ids:
        want = set(args.ids)
        unknown = want - {x["id"] for x in items}
        if unknown:
            raise SystemExit(f"ABORT: unknown ids for split {args.split}: {sorted(unknown)}")
        items = [x for x in items if x["id"] in want]
    out = Path(args.out).resolve()
    raw_dir = out / "raw"
    done = [x for x in items if (raw_dir / f"{x['id']}.json").exists()]
    bad = []
    for x in done:
        prev = json.loads((raw_dir / f"{x['id']}.json").read_text())
        if prev["dispatch_order"] != orders[x["id"]]:
            bad.append(x["id"])
    retr = Counter()
    for x in items:
        for m, r in C.retriever_assignment(C.agent_view(x)).items():
            retr[(m, r)] += 1
    p = {"split": args.split, "items_in_split": len(all_items), "items_planned": len(items), "already_collected": len(done),
         "to_collect": len(items) - len(done), "resume_dispatch_mismatch": bad[:5],
         "retriever_counts": {f"{m}/{r}": n for (m, r), n in sorted(retr.items())},
         "first_dispatch_orders": {x["id"]: orders[x["id"]] for x in items[:3]},
         "out": str(out), "list_order": MODELS_V6}
    # the section 4.1 inheritance: v6 position k takes v5 position k's dispatch slot and retriever (checked on v5's own raw records)
    v5raw = V5 / "results" / ("conf" if args.split == "conf" else "dev") / "raw"
    if v5raw.exists():
        v5m = C_V5_MODELS
        diff_order = diff_ret = n = 0
        for x in items:
            f = v5raw / f"{x['id']}.json"
            if not f.exists():
                continue
            r5 = json.loads(f.read_text())
            n += 1
            diff_order += [MODELS_V6[v5m.index(m)] for m in r5["dispatch_order"]] != orders[x["id"]]
            ar = C.retriever_assignment(C.agent_view(x))
            diff_ret += any(ar[MODELS_V6[v5m.index(m)]] != r for m, r in r5["retriever_assignment"].items())
        p["slot_inheritance_vs_v5_raw"] = {"items_compared": n, "dispatch_order_differs": diff_order, "retriever_differs": diff_ret}
    return p, bad


C_V5_MODELS = ["llama3.2:3b", "mistral", "gemma2:2b", "phi3:mini", "qwen2.5:3b"]   # v5's frozen list, for the inheritance check


# ── cli ─────────────────────────────────────────────────────────

def under_v6_results(p):
    p = Path(p).resolve()
    return (V6 / "results") in p.parents


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    sub = argv[0] if argv and argv[0] in ("audit", "judge-inputs", "build-dense") else ""
    if sub == "build-dense":
        sys.exit("ABORT: v6 reuses the v5 dense index unchanged")
    if "--out" not in argv:
        sys.exit("ABORT: v6 requires an explicit --out under real-agent-eval/v6/results/")
    out = argv[argv.index("--out") + 1] if argv.index("--out") + 1 < len(argv) else ""
    if not out or not under_v6_results(out):
        sys.exit(f"ABORT: --out {out!r} is not under {V6 / 'results'}")
    if sub:
        sys.argv = [sys.argv[0]] + argv           # audit / judge-inputs: raw records only, no Ollama
        return C.main()
    ap = argparse.ArgumentParser(description="eval v6 collector (v5 collector, v6 pool)")
    ap.add_argument("--split", choices=["dev", "conf"], required=True)
    ap.add_argument("--n-items", type=int)
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=int, default=C.TIMEOUT_S)
    ap.add_argument("--mixed-fleet", action="store_true")
    ap.add_argument("--verify-index", action="store_true")
    ap.add_argument("--run", action="store_true", help="actually collect (calls Ollama); without it: checks, plan, then refuse")
    args = ap.parse_args(argv)
    if args.mixed_fleet:
        sys.exit("ABORT: v6 has no mixed-fleet arm (prereg section 4.3)")
    if args.split == "conf" and args.n_items not in (None, 1100) and not args.ids:
        sys.exit("ABORT: v6 conf collects the frozen 1,100 items (--n-items 1100)")

    checks = [("pool_manifest", check_pool_manifest), ("digests_vs_manifest (offline)", check_digests_offline),
              ("freeze", lambda: check_freeze(args.split)), ("corpus_and_index_hashes", lambda: check_corpus(args.split)),
              ("disk", check_disk)]

    def run_checks(cs):
        res = []
        for name, fn in cs:
            try:
                ok, detail = fn()
            except SystemExit as e:
                ok, detail = False, str(e)
            except Exception as e:            # a failing check is a failed check, never a crash that skips the rest
                ok, detail = False, f"{type(e).__name__}: {e}"
            res.append((name, ok, detail))
        return res

    results = run_checks(checks)
    pl, bad = plan(args)
    if bad:
        results.append(("resume_dispatch_order", False, f"existing raw records disagree with the v6 dispatch order: {bad[:3]}"))
    inh = pl.get("slot_inheritance_vs_v5_raw")
    if inh and (inh["dispatch_order_differs"] or inh["retriever_differs"]):
        results.append(("slot_inheritance", False, str(inh)))
    elif inh:
        results.append(("slot_inheritance", True, f"{inh['items_compared']} items: v6 dispatch order and retriever = v5's by list position"))
    failed = [n for n, ok, _ in results if not ok]
    if not args.run:
        print("DRY RUN (no --run): nothing is collected and Ollama is not contacted.")
    for n, ok, d in results:
        print(f"[{'ok' if ok else 'FAIL'}] {n}: {d}")
    print(json.dumps(pl, indent=1))
    if not args.run:
        print("REFUSED: pass --run to collect." + (f" Failing checks: {failed}" if failed else " All checks pass."))
        return 2
    if failed:
        sys.exit(f"ABORT: start-up checks failed: {failed}")
    (n, ok, d), = run_checks([("ollama_live", check_live)])      # the first contact with Ollama, only after every offline check passed
    print(f"[{'ok' if ok else 'FAIL'}] {n}: {d}")
    if not ok:
        sys.exit(f"ABORT: {d}")
    # run mode: the embedder digest on top of v5's own start-up checks (digests of the five agents, corpus, freeze)
    orig_verify = C.verify_digests

    def verify_digests(need_embed):
        out_ = orig_verify(need_embed)
        want = json.loads(C.V3_MANIFEST.read_text())["model_digests"][EMBED_TAG]["digest"]
        if need_embed and out_[C.EMBED_MODEL]["digest"] != want:
            sys.exit(f"ABORT: embedder digest {out_[C.EMBED_MODEL]['digest'][:12]} differs from pool_manifest.json {want[:12]}")
        return out_

    C.verify_digests = verify_digests
    sys.argv = [sys.argv[0]] + [a for a in argv if a != "--run"]
    return C.main()


if __name__ == "__main__":
    sys.exit(main())
