#!/usr/bin/env python3
"""EXPLORATORY, outside the preregistration.

MiniCheck fails the preregistered three-way macro-F1 criterion by construction (binary checker) and
meets every supports criterion; this re-decision is outside the preregistration.

Re-decides the v5 confirmatory items with MiniCheck labels (checks_minicheck.jsonl, checker
98751cc0…) in place of the hosted checker 0.2.0 (f2a14bd8…), using the frozen logic only:
  * evaluate_v5.py (frozen, imported read-only) rebuilds every item (prepare_item, python_methods);
  * selector_study.decide (which reproduces every published decision) gives VV, BE-G, VV/VDF and
    BE-G/VDF; selector_study.summarize / h3a give accuracy, b/c vs MAJ, c_D, F and the H3a bound.
The hosted run is recomputed side by side through the same code and must reproduce the published
P/T numbers, else ABORT. Nothing is modified; no model or hosted call is made.

Writes results.json next to this file. Run:
  python3 real-agent-eval/v5/local_checker/minicheck_redecide.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
V5 = HERE.parent
sys.path[:0] = [str(V5), str(V5 / "selector_study")]
import evaluate_v5 as E  # noqa: E402  frozen
import selector_study as S  # noqa: E402

CONF = V5 / "results" / "conf"
MC_ID = "98751cc07911d57a1586848dfb8c4e7b"
METHODS = ["VV", "BE-G", "VV/VDF", "BE-G/VDF"]
LABEL = ("MiniCheck fails the preregistered three-way macro-F1 criterion by construction (binary checker) "
         "and meets every supports criterion; this re-decision is outside the preregistration")


def build(checks_path, accepted, items, raws, TWW):
    from types import SimpleNamespace
    ctx = E.Ctx(SimpleNamespace(strict=True), E.load_captures(CONF / "captures.jsonl"), E.load_checks(checks_path),
                {}, accepted=accepted)
    rows, audits = [], {}
    for iid in sorted(raws, key=lambda i: (items[i].get("order", 0), i)):
        rec = E.prepare_item(items[iid], raws[iid], ctx)
        row = rec["row"]
        row["set"] = E.analysis_set(rec["item"], strict=True)
        if not row["eligible"]:
            continue
        E.python_methods(rec, ctx, E.PREREG_BEST)
        ch, meta, defaults = S.decide(rec, ctx, TWW)
        r = {"id": iid, "set": row["set"], "decisive": row["decisive"], "MAJ": row["MAJ"], "MAJ_obj": row["MAJ_obj"],
             "_meta": meta, "_defaults": defaults}
        for k, o in ch.items():
            r[k] = E.object_correct(rec, o)[0]
            r[k + "_obj"] = o
        rows.append(r)
        for v in rec["parsed"]:
            for a in v["audit"]:
                # licensing = an accepted, status-ok `supports` label on the answer's value (after the
                # binary REFUTED swap), i.e. what makes the answer a gate witness
                audits[(iid, v["agent"], a["passage_key"])] = {
                    "lic": bool(a.get("support_label") == "supports" and a.get("support_status") == "ok"
                                and a.get("accepted")),
                    "label": a.get("support_label"), "check": a.get("check"), "value": v["parsed"]}
    return rows, audits


def stats(rows):
    dec = [r for r in rows if r["decisive"]]
    out = {}
    for s in ("P", "T"):
        rs = [r for r in dec if r["set"] == s]
        out[s] = {"n": len(rs), "MAJ_acc": sum(r["MAJ"] for r in rs) / len(rs)}
        for m in METHODS:
            o = S.summarize(rs, m, rs[0]["_defaults"][m])
            d = {"acc": o["acc"], "b_vs_MAJ": o["b_vs_MAJ"], "c_vs_MAJ": o["c_vs_MAJ"], "default": o["default"],
                 "c_D": o["c_vs_D"], "F": o.get("F"), "harm_bound_holds": o.get("harm_bound_holds"),
                 "p_exact_mcnemar_vs_MAJ": o["p_exact_mcnemar_vs_MAJ"], "c_D_items": o["c_vs_D_items"]}
            if s == "P":
                h = S.h3a(rs, m)
                d["H3a"] = {"n_R": h["n_R"], "c": h["c"], "ub": h["cp_upper_97_5"], "reject": h["reject"]}
            out[s][m] = d
    return out


def main():
    TWW, _, _ = S.dev_trust_weights()
    items = E.load_items(V5 / "benchmark" / "items_confirmatory.jsonl")
    raws = {f.stem: E.jload(f) for f in sorted((CONF / "raw").glob("*.json"))}
    hrows, haud = build(CONF / "checks.jsonl", [E.PREREG_CHECKER], items, raws, TWW)
    mrows, maud = build(HERE / "checks_minicheck.jsonl", [MC_ID], items, raws, TWW)
    hs, ms = stats(hrows), stats(mrows)
    # reproduction gate for the hosted side (selector_study README table)
    want = {"P": {"BE-G": (0.8650, 91, 12, 10), "VV": (0.8650, 88, 9, 9)}, "T": {"BE-G": (0.5652, 9, 1, 0)}}
    for s, mm in want.items():
        for m, (acc, b, c, cd) in mm.items():
            g = hs[s][m]
            if (round(g["acc"], 4), g["b_vs_MAJ"], g["c_vs_MAJ"], g["c_D"]) != (acc, b, c, cd):
                raise SystemExit(f"ABORT: hosted {s} {m} not reproduced: {g}")
    assert set(haud) == set(maud)
    # licensing-label differences, per cited (item, agent, passage) citation
    pairs = Counter((haud[k]["lic"], maud[k]["lic"]) for k in haud)
    # per unique check (proposition, passage), raw labels
    hk = {json.loads(l)["check_key"]: json.loads(l) for l in open(CONF / "checks.jsonl")}
    mk = {json.loads(l)["check_key"]: json.loads(l) for l in open(HERE / "checks_minicheck.jsonl")}
    raw = Counter((hk[k]["label"] or hk[k]["status"], mk[k]["label"] or mk[k]["status"]) for k in mk)
    # items whose decision changed
    hb, mb = {r["id"]: r for r in hrows}, {r["id"]: r for r in mrows}
    changed = {m: {s: sum(1 for i in hb if hb[i]["decisive"] and hb[i]["set"] == s and hb[i][m + "_obj"] != mb[i][m + "_obj"])
                   for s in ("P", "T")} for m in METHODS}
    calls = [json.loads(l) for l in open(HERE / "check_calls_minicheck.jsonl")]
    ms_total = sum(c.get("duration_ms") or 0 for c in calls)
    n_elig = len(mrows)
    res = {"label": LABEL, "exploratory": True,
           "evaluator_sha256": E.sha256_file(E.__file__),
           "hosted_checker": E.PREREG_CHECKER, "minicheck_checker": MC_ID,
           "hosted": hs, "minicheck": ms,
           "decisions_changed_vs_hosted": changed,
           "licensing_citations": {"n": sum(pairs.values()), "both": pairs[(True, True)],
                                   "hosted_only": pairs[(True, False)], "minicheck_only": pairs[(False, True)],
                                   "neither": pairs[(False, False)],
                                   "differ": pairs[(True, False)] + pairs[(False, True)]},
           "raw_labels_per_check_hosted_x_minicheck": {f"{a}|{b}": n for (a, b), n in sorted(raw.items())},
           "cost": {"hosted_usd_per_decision": 0.0, "minicheck_calls": len(calls),
                    "local_check_seconds_total": round(ms_total / 1000, 1),
                    "eligible_decisions": n_elig,
                    "local_check_seconds_per_eligible_decision": round(ms_total / 1000 / n_elig, 2),
                    "hosted_checker_reference": "P $0.0211 / decision (RUN_NOTES item 9)"}}
    with open(HERE / "results.json", "w") as f:
        json.dump(res, f, indent=1, sort_keys=True)
    for s in ("P", "T"):
        for m in METHODS:
            h, k = hs[s][m], ms[s][m]
            print(f"{s} {m:9} hosted acc {h['acc']:.4f} b/c {h['b_vs_MAJ']}/{h['c_vs_MAJ']} cD {h['c_D']} F {h['F']}"
                  f" ub {h.get('H3a', {}).get('ub', 0):.4f} | MC acc {k['acc']:.4f} b/c {k['b_vs_MAJ']}/{k['c_vs_MAJ']}"
                  f" cD {k['c_D']} F {k['F']} ub {k.get('H3a', {}).get('ub', 0):.4f} rej {k.get('H3a', {}).get('reject')}"
                  f" changed {changed[m][s]}")
    print(json.dumps({k: res[k] for k in ("licensing_citations", "raw_labels_per_check_hosted_x_minicheck", "cost")}, indent=1))


if __name__ == "__main__":
    main()
