#!/usr/bin/env python3
"""Checker prompt-stability test for v5 (PREPARED, NOT RUN; post hoc, exploratory). See SPEC.md.

  plan     no hosted call: load the pair population (../stability_population.jsonl, written by
           ../harm_attribution.py), reproduce each original prompt (internal_check_key), render the
           k = 3 paraphrased prompts, check the length limits, count calls and estimate cost
  run      hosted calls (checker 0.2.0 model / flags / pinned CLI, paraphrased template). Refuses
           to start without --i-approve-hosted-cost. Logs every call to calls.jsonl here.
  analyze  per paraphrase: label flip rate (Wilson 95%), exact McNemar vs the sealed label; then
           BE-G / VV (and VDF variants) re-decided with the frozen logic under
           "supports only if supports under every paraphrase" and under each paraphrase alone

Run: DISABLE_AUTOUPDATER=1 python3 -I real-agent-eval/v5/harm_attribution/stability/checker_stability.py <cmd>
Never writes into the support store, checks.jsonl, the cache, or any frozen file.
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
HA = HERE.parent
V5 = HA.parent
ROOT = V5.parent.parent
SUPPORT = ROOT / "tools" / "evidence" / "support"
sys.path.insert(0, str(SUPPORT))
sys.path.insert(0, str(SUPPORT.parent))
sys.path.insert(0, str(HA))
import check as CK  # noqa: E402  hosted checker 0.2.0 (read-only use)

CHECKER_ID = "f2a14bd8988371bd231ca6ff137be13e"
# Install CLI 2.1.307 on PATH or set BRAN_CLAUDE_BIN; checker_id verifies the pin.
CLAUDE_BIN = os.path.expanduser(os.environ.get("BRAN_CLAUDE_BIN", "claude"))   # pinned client of the conf run
POP = HA / "stability_population.jsonl"
CHECKS = V5 / "results" / "conf" / "checks.jsonl"
TEMPLATES = {f"para{i}": HERE / "templates" / f"paraphrase_{i}.txt" for i in (1, 2, 3)}
ORIGINAL = "orig_rerun"            # optional: the unchanged template re-run (sampling-noise baseline)
PLAN = HERE / "plan.json"
CALLS = HERE / "calls.jsonl"
USD_PER_CHECK = 0.0048             # results/conf/RUN_NOTES.md item 9 (mean cited check)
DEFAULT_MAX_USD = 6.0


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def read_jsonl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def load_population():
    pop = read_jsonl(POP)
    need = {p["check_key"] for p in pop}
    checks = {}
    for l in open(CHECKS, encoding="utf-8"):
        e = json.loads(l)
        if e["check_key"] in need:
            checks[e["check_key"]] = e
    missing = need - set(checks)
    if missing:
        raise SystemExit(f"ABORT: {len(missing)} population checks not in checks.jsonl")
    return pop, checks


def templates(include_original):
    t = {name: CK.load_template(str(p)) for name, p in TEMPLATES.items()}
    if include_original:
        t[ORIGINAL] = CK.load_template()
    return t


def prompts(pop, checks, tmpl):
    """{(condition, check_key): user prompt}; verifies the original prompt first."""
    orig = CK.load_template()
    out = {}
    for ck in sorted({p["check_key"] for p in pop}):
        e = checks[ck]
        if e["status"] != "ok" or e["checker"]["checker_id"] != CHECKER_ID:
            raise SystemExit(f"ABORT: {ck} not an ok check of the accepted checker")
        spans = [sp["text"] for sp in e["spans"]]
        u0 = CK.render_user(orig, e["proposition_text"], spans)
        k0 = CK.sha256_hex16(CK.canonical_bytes({"checker_id": CHECKER_ID, "prompt_sha256": CK.sha256_hex(u0.encode())}))
        if k0 != e["internal_check_key"]:
            raise SystemExit(f"ABORT: original prompt not reproduced for {ck}")
        for name, t in tmpl.items():
            out[(name, ck)] = CK.render_user(t, e["proposition_text"], spans)
    return out


# ── plan (no hosted call) ───────────────────────────────────────

def cmd_plan(args):
    pop, checks = load_population()
    tmpl = templates(include_original=True)
    pr = prompts(pop, checks, tmpl)
    too_long = sorted(k for k, u in pr.items() if len(u) > CK.MAX_PROMPT_CHARS)
    n_ck = len({p["check_key"] for p in pop})
    k = len(TEMPLATES)
    plan = {"note": "POST HOC, exploratory. Prepared, not run.",
            "pairs": len(pop), "distinct_checks": n_ck, "k": k,
            "templates": {n: {"path": str(TEMPLATES.get(n, SUPPORT / "prompt_template.txt").relative_to(ROOT)),
                              "sha256": t["sha256"], "system_chars": len(t["system"])} for n, t in tmpl.items()},
            "pairs_by_why": dict(Counter(w for p in pop for w in p["why"])),
            "pairs_by_set": dict(Counter(p["set"] for p in pop)),
            "pairs_by_source": dict(Counter(p["source"] for p in pop)),
            "prompts_over_MAX_PROMPT_CHARS": too_long,
            "calls_paraphrases": k * n_ck, "usd_per_check": USD_PER_CHECK,
            "estimated_usd_paraphrases": round(k * n_ck * USD_PER_CHECK, 2),
            "calls_with_original_rerun": (k + 1) * n_ck,
            "estimated_usd_with_original_rerun": round((k + 1) * n_ck * USD_PER_CHECK, 2),
            "prompt_sha256": {f"{c}:{ck}": sha(u) for (c, ck), u in sorted(pr.items())}}
    with open(PLAN, "w") as f:
        json.dump(plan, f, indent=1, sort_keys=True)
    print(json.dumps({k_: v for k_, v in plan.items() if k_ != "prompt_sha256"}, indent=1))
    return 0


# ── run (hosted; gated) ─────────────────────────────────────────

def cmd_run(args):
    if not args.i_approve_hosted_cost:
        raise SystemExit("REFUSED: this makes hosted checker calls (see plan.json for the cost). "
                         "Re-run with --i-approve-hosted-cost once the cost is approved.")
    if os.environ.get("DISABLE_AUTOUPDATER") != "1":
        raise SystemExit("ABORT: set DISABLE_AUTOUPDATER=1")
    ref = CK.Checker(claude_bin=CLAUDE_BIN)              # the sealed checker: pins CLI, model, flags
    if ref.checker_id != CHECKER_ID:
        raise SystemExit(f"ABORT: checker_id {ref.checker_id} != {CHECKER_ID} (wrong CLI or edited checker)")
    pop, checks = load_population()
    tmpl = templates(args.include_original)
    pr = prompts(pop, checks, tmpl)
    checkers = {n: CK.Checker(claude_bin=CLAUDE_BIN, template=t) for n, t in tmpl.items()}
    for n, c in checkers.items():
        assert c.flags_sha256 == ref.flags_sha256 and c.pin == ref.pin, n
    done = {}
    if CALLS.exists():
        for e in read_jsonl(CALLS):
            if e["status"] in CK.CACHEABLE:
                done[(e["condition"], e["check_key"])] = e
    pending = [(k, u) for k, u in sorted(pr.items()) if k not in done and len(u) <= CK.MAX_PROMPT_CHARS]
    spent = [sum(e.get("cost_usd") or 0 for e in read_jsonl(CALLS))] if CALLS.exists() else [0.0]
    proj = spent[0] + len(pending) * USD_PER_CHECK
    if proj > args.max_usd:
        raise SystemExit(f"ABORT: projected ${proj:.2f} > --max-usd {args.max_usd}")
    print(f"pending={len(pending)} done={len(done)} spent=${spent[0]:.4f} projected=${proj:.2f}", file=sys.stderr)
    lock = threading.Lock()

    def one(job):
        (cond, ck), user = job
        chk = checkers[cond]
        for attempt in range(3):
            with lock:
                if spent[0] >= args.max_usd - 0.05:
                    return
            res = chk.call(user)
            row = {"condition": cond, "check_key": ck, "checker_id": chk.checker_id,
                   "template_sha256": chk.template["sha256"], "flags_sha256": chk.flags_sha256,
                   "prompt_sha256": sha(user), "status": res["status"], "label": res.get("label"),
                   "score_q": res.get("score_q"), "model_reported": res.get("model_reported"),
                   "cost_usd": res.get("cost_usd"), "duration_ms": res.get("duration_ms"), "attempt": attempt,
                   "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            with lock:
                spent[0] += res.get("cost_usd") or 0.0
                with open(CALLS, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, sort_keys=True) + "\n")
            if res["status"] in CK.CACHEABLE:
                return
            time.sleep(2 * (attempt + 1))

    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for n, _ in enumerate(ex.map(one, pending), 1):
            if n % 50 == 0:
                print(f"  {n}/{len(pending)} ${spent[0]:.3f} {time.time() - t0:.0f}s", file=sys.stderr)
    print(f"done: spent_total=${spent[0]:.4f} wall={time.time() - t0:.0f}s", file=sys.stderr)
    return 0


# ── analyze (no hosted call) ────────────────────────────────────

def cmd_analyze(args):
    import harm_attribution as HAm
    E = HAm.E
    PR = E.PR
    pop, checks = load_population()
    calls = Path(args.calls) if args.calls else CALLS
    lab = {}
    for e in read_jsonl(calls):
        if e["status"] == "ok":
            lab[(e["condition"], e["check_key"])] = e["label"]   # last ok answer per (condition, check)
    conds = [c for c in list(TEMPLATES) + [ORIGINAL] if any(k[0] == c for k in lab)]
    paras = [c for c in TEMPLATES if c in conds]

    def mapped(cond, p):
        raw = lab.get((cond, p["check_key"]))
        return None if raw is None else PR.map_label(raw, p["label_map"])

    out = {"note": "POST HOC, exploratory.", "calls_file": str(calls), "conditions": conds, "per_condition": {}}
    for c in conds:
        rows = [(p, mapped(c, p)) for p in pop]
        have = [(p, m) for p, m in rows if m is not None]
        flips = sum(1 for _, m in have if m != "supports")
        # McNemar vs the sealed label on the binary supports / not-supports scale. Every sealed label in
        # the population is `supports`, so the not->supports cell is 0 by construction.
        b, cc = flips, 0
        by_grp = {}
        for grp, pred in (("licensing", lambda p: "supported_wrong" not in p["why"]),
                          ("supported_wrong", lambda p: "supported_wrong" in p["why"]),
                          ("correct_value", lambda p: p["correct"]), ("wrong_value", lambda p: not p["correct"])):
            g = [m for p, m in have if pred(p)]
            f = sum(1 for m in g if m != "supports")
            by_grp[grp] = {"n": len(g), "flips": f, "flip_rate": f / len(g) if g else None,
                           "wilson95": E.wilson(f, len(g)) if g else None}
        out["per_condition"][c] = {"n_pairs": len(pop), "n_with_label": len(have), "missing": len(pop) - len(have),
                                   "label_dist": dict(Counter(m for _, m in have)), "flips": flips,
                                   "flip_rate": flips / len(have) if have else None,
                                   "flip_wilson95": E.wilson(flips, len(have)) if have else None,
                                   "mcnemar_b_supports_to_not": b, "mcnemar_c_not_to_supports": cc,
                                   "mcnemar_exact_p": E.mcnemar_p(b, cc), "by_group": by_grp}
    # decisions
    W = HAm.World()
    base_rows, _ = HAm.build_rows(W)
    base = HAm.decisive_sets(base_rows)
    key = lambda p: (p["item_id"], p["passage_key"], p["proposition_text"])
    scen = {}
    if paras:
        scen["supports_under_all_k"] = frozenset(
            key(p) for p in pop if any(mapped(c, p) not in (None, "supports") for c in paras))
        out["all_k_missing_kept_original"] = sum(1 for p in pop if any(mapped(c, p) is None for c in paras))
    for c in conds:
        scen[f"{c}_alone"] = frozenset(key(p) for p in pop if mapped(c, p) not in (None, "supports"))
    out["decisions"] = {}
    for name, fl in scen.items():
        rows, matched = HAm.build_rows(W, fl) if fl else (base_rows, {})
        sets = HAm.decisive_sets(rows)
        d = {"pairs_set_to_NEI": len(fl)}
        for s in ("P", "T"):
            d[s] = {}
            for m, dk in HAm.METHODS.items():
                b0 = HAm.method_block(base[s], m, dk)
                nb = HAm.method_block(sets[s], m, dk)
                d[s][m] = {"acc": nb["acc"], "b_vs_MAJ": nb["b_vs_MAJ"], "c_vs_MAJ": nb["c_vs_MAJ"], "c_D": nb["c_D"],
                           "overturn_rate_cp_upper_97_5": nb["overturn_of_right_majorities"]["cp_upper_97_5"],
                           "vs_sealed": HAm.diff_block(b0, nb)}
        out["decisions"][name] = d
    dst = Path(args.out) if args.out else HERE / "stability_results.json"
    with open(dst, "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    for c, o in out["per_condition"].items():
        print(f"{c:12} n={o['n_with_label']:4} flips={o['flips']:4} rate={o['flip_rate'] or 0:.3f} "
              f"mcnemar_p={o['mcnemar_exact_p']:.3g}")
    for name, d in out["decisions"].items():
        for s in ("P", "T"):
            for m in ("BE-G", "VV"):
                o = d[s][m]
                print(f"{name:22} {s} {m:5} acc={o['acc']:.4f} b={o['b_vs_MAJ']} c={o['c_vs_MAJ']} c_D={o['c_D']} "
                      f"UB={o['overturn_rate_cp_upper_97_5']:.4f}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan").set_defaults(fn=cmd_plan)
    r = sub.add_parser("run")
    r.add_argument("--i-approve-hosted-cost", action="store_true",
                   help="required: confirms the hosted cost in plan.json has been approved")
    r.add_argument("--include-original", action="store_true",
                   help="also re-run the unchanged template once per check (sampling-noise baseline)")
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--max-usd", type=float, default=DEFAULT_MAX_USD)
    r.set_defaults(fn=cmd_run)
    a = sub.add_parser("analyze")
    a.add_argument("--calls", help="calls file (default: calls.jsonl here)")
    a.add_argument("--out", help="output path (default: stability_results.json here)")
    a.set_defaults(fn=cmd_analyze)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
