#!/usr/bin/env python3
"""
Harm attribution on the v5 confirmatory data (POST HOC, exploratory; NOT confirmatory).

Reuses the reconstruction of ../selector_study/selector_study.py, which imports the frozen
evaluate_v5.py unedited and reproduces every published per-item decision. No model, hosted or
Rust-binary call is made. Nothing outside this directory is written.

  1. per-source harm breakdown (BE-G, VV, BE-G/VDF, VV/VDF) on decisive P and T items
  2. label-replay attribution: the accepted `supports` labels of the verified-wrong pairs of one
     error class (controls/harm_reading.jsonl) are set to not_enough_info on the sealed support
     records (value level, everything else fixed); BE-G / VV (and VDF variants) are re-decided
     with the frozen logic
  3. judge errors (J) vs F items on P: 2x2 table, Fisher's exact test
  4. the pair population for the (not run) checker prompt-stability test, see checker_stability.py

Usage: python3 real-agent-eval/v5/harm_attribution/harm_attribution.py   (writes results.json)
"""
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
V5 = HERE.parent
sys.path.insert(0, str(V5 / "selector_study"))
import selector_study as S  # noqa: E402  reconstruction (imports the frozen evaluator read-only)

E = S.E
CONF_DIR = S.CONF_DIR
HARM = V5 / "controls" / "harm_reading.jsonl"
NEI = "not_enough_info"
METHODS = {"BE-G": "D", "VV": "MAJ", "BE-G/VDF": "D", "VV/VDF": "MAJ"}   # method -> its own default
SOURCES = {"P": ["scifact", "popqa", "fever"], "T": ["truthfulqa"]}


# ── reconstruction with optional label replay ───────────────────

class World:
    def __init__(self):
        self.TWW, _, _ = S.dev_trust_weights()
        self.ctx = S.make_ctx(CONF_DIR / "captures.jsonl", CONF_DIR / "checks.jsonl")
        self.items = E.load_items(V5 / "benchmark" / "items_confirmatory.jsonl")
        self.raws = {f.stem: E.jload(f) for f in sorted((CONF_DIR / "raw").glob("*.json"))}
        self.pub = {r["id"]: r for r in csv.DictReader(open(CONF_DIR / "eval" / "paired_decisions_v5.csv"))}
        self.order = sorted(self.raws, key=lambda i: (self.items[i].get("order", 0), i))


def apply_flips(rec, flips, matched):
    """Set the accepted, status-ok `supports` label of every flipped (item, passage, proposition)
    to not_enough_info, on the citation audit AND on the sealed support record the reducer reads.
    Value level: the support record is per contribution, so a binary item's other value (which
    shares the check) keeps its label."""
    iid = rec["item"]["id"]
    for v in rec["parsed"]:
        for e, a in zip(v["evidence"], v["audit"]):
            key = (iid, a["passage_key"], v["prop"]["text"])
            if key not in flips:
                continue
            if a.get("support_label") == "supports" and a.get("support_status") == "ok" and a.get("accepted"):
                sup = rec["store"]["support"][e["support_ref"]]
                assert sup["label"] == "supports" and sup["contribution_id"] == v["_id"]
                sup["label"] = NEI
                a["support_label"] = NEI
                matched[key].append({"agent": v["agent"], "value": v["parsed"], "correct": v["correct"]})


def build_rows(W, flips=frozenset(), check_pub=False, keep_pairs=False):
    rows, mism = [], []
    matched = defaultdict(list)
    for iid in W.order:
        rec = E.prepare_item(W.items[iid], W.raws[iid], W.ctx)
        row = rec["row"]
        row["set"] = E.analysis_set(rec["item"], strict=True)
        if not row["eligible"]:
            continue
        if flips:
            apply_flips(rec, flips, matched)
        E.python_methods(rec, W.ctx, E.PREREG_BEST)
        ch, meta, defaults = S.decide(rec, W.ctx, W.TWW)
        r = {"id": iid, "set": row["set"], "source": row["source"], "decisive": row["decisive"],
             "MAJ": row["MAJ"], "MAJ_obj": row["MAJ_obj"], "majority_tied": row["majority_tied"], "_meta": meta,
             "F": E.f_and_pairs(rec, W.ctx.accepted)[0]}
        for k, o in ch.items():
            r[k] = E.object_correct(rec, o)[0]
            r[k + "_obj"] = o
        if check_pub:
            p = W.pub[iid]
            for col in ("MAJ", "VV", "BE-G", "D"):
                if str(r[col]) != p[col] or str(r[col + "_obj"]) != p[col + "_obj"]:
                    mism.append((iid, col))
            r["J"] = int(p["J"])
            r["J_nullwrong"] = int(p["J_nullwrong"])
            r["J_fallback"] = int(p["J_fallback"])
        if keep_pairs:
            # every accepted, status-ok citation (value-mapped label), for the stability population
            r["_pairs"] = [{"value": v["parsed"], "norm": E.norm_obj(v["parsed"]), "agent": v["agent"],
                            "correct": bool(v["correct"]), "passage_key": a["passage_key"], "check_key": a["check"],
                            "proposition_text": v["prop"]["text"], "label_map": v["prop"]["label_map"],
                            "mapped_label": a["support_label"]}
                           for v in rec["parsed"] for a in v["audit"]
                           if a.get("support_status") == "ok" and a.get("accepted")]
        rows.append(r)
    if mism:
        raise SystemExit(f"ABORT: reconstruction mismatch {mism[:10]} ({len(mism)})")
    return rows, matched


def decisive_sets(rows):
    dec = [r for r in rows if r["decisive"]]
    return {s: [r for r in dec if r["set"] == s] for s in ("P", "T")}


# ── statistics ──────────────────────────────────────────────────

def rate_block(c, n):
    return {"c": c, "n_R": n, "rate": c / n if n else None, "wilson95": E.wilson(c, n) if n else None,
            "cp_upper_97_5": E.cp_upper(c, n, E.H3A_ALPHA) if n else None}


def method_block(rs, m, dkey):
    n = len(rs)
    right = [r for r in rs if r["MAJ"]]
    c = sum(1 for r in right if not r[m])
    b = sum(1 for r in rs if r[m] and not r["MAJ"])
    cD = sorted(r["id"] for r in rs if r[dkey] and not r[m])
    out = {"n": n, "acc_MAJ": sum(r["MAJ"] for r in rs) / n if n else None,
           "acc": sum(r[m] for r in rs) / n if n else None, "b_vs_MAJ": b, "c_vs_MAJ": c,
           "default": dkey, "c_D": len(cD), "c_D_items": cD,
           "c_vs_MAJ_items": sorted(r["id"] for r in right if not r[m]),
           "b_vs_MAJ_items": sorted(r["id"] for r in rs if r[m] and not r["MAJ"]),
           "overturn_of_right_majorities": rate_block(c, len(right))}
    return out


def fisher_exact(a, b, c, d):
    """2x2 [[a, b], [c, d]]: two-sided (sum of tables with prob <= observed) and one-sided
    (greater: P(X >= a)) hypergeometric p-values, plus the sample odds ratio."""
    r1, r2, c1, n = a + b, c + d, a + c, a + b + c + d
    lo, hi = max(0, c1 - r2), min(r1, c1)
    lp = lambda x: (math.lgamma(r1 + 1) - math.lgamma(x + 1) - math.lgamma(r1 - x + 1) + math.lgamma(r2 + 1)
                    - math.lgamma(c1 - x + 1) - math.lgamma(r2 - c1 + x + 1) - math.lgamma(n + 1)
                    + math.lgamma(c1 + 1) + math.lgamma(n - c1 + 1))
    probs = {x: math.exp(lp(x)) for x in range(lo, hi + 1)}
    p0 = probs[a]
    two = min(1.0, sum(p for p in probs.values() if p <= p0 * (1 + 1e-7)))
    greater = min(1.0, sum(p for x, p in probs.items() if x >= a))
    orr = (a * d) / (b * c) if b * c else float("inf")
    return {"p_two_sided": two, "p_greater": greater, "odds_ratio": orr, "expected_a_under_independence": r1 * c1 / n}


# ── step 1 ──────────────────────────────────────────────────────

def per_source(sets):
    out = {}
    for m, dkey in METHODS.items():
        out[m] = {}
        for s, rs in sets.items():
            out[m][s] = {"all": method_block(rs, m, dkey)}
            for src in SOURCES[s]:
                out[m][s][src] = method_block([r for r in rs if r["source"] == src], m, dkey)
            assert sum(out[m][s][src]["n"] for src in SOURCES[s]) == len(rs)
    return out


# ── step 2 ──────────────────────────────────────────────────────

def harm_pairs():
    hr = [json.loads(l) for l in open(HARM)]
    return hr


def scenario_flips(hr, pred):
    return frozenset((h["item_id"], h["passage_key"], h["proposition"]) for h in hr if pred(h))


SCENARIOS = {
    "K": lambda h: h["cls"] == "K",
    "E": lambda h: h["cls"] == "E",
    "S": lambda h: h["cls"] == "S",
    "G": lambda h: h["cls"] == "G",
    "G:alias": lambda h: h["cls"] == "G" and h["gold_subclass"] == "alias",
    "G:alternative": lambda h: h["cls"] == "G" and h["gold_subclass"] == "alternative",
    "G:disagreement": lambda h: h["cls"] == "G" and h["gold_subclass"] == "disagreement",
    "K+E": lambda h: h["cls"] in ("K", "E"),
    "K+E+S": lambda h: h["cls"] in ("K", "E", "S"),
    "all (K+E+S+G)": lambda h: True,
}


def diff_block(base, new):
    bc, nc = set(base["c_vs_MAJ_items"]), set(new["c_vs_MAJ_items"])
    bb, nb = set(base["b_vs_MAJ_items"]), set(new["b_vs_MAJ_items"])
    bd, nd = set(base["c_D_items"]), set(new["c_D_items"])
    return {"d_acc": new["acc"] - base["acc"], "d_b_vs_MAJ": new["b_vs_MAJ"] - base["b_vs_MAJ"],
            "d_c_vs_MAJ": new["c_vs_MAJ"] - base["c_vs_MAJ"], "d_c_D": new["c_D"] - base["c_D"],
            "harms_vs_MAJ_removed": sorted(bc - nc), "new_harms_vs_MAJ": sorted(nc - bc),
            "corrections_lost": sorted(bb - nb), "new_corrections": sorted(nb - bb),
            "c_D_removed": sorted(bd - nd), "new_c_D": sorted(nd - bd)}


def attribution(W, base_sets, hr):
    base = {m: method_block(base_sets["P"], m, d) for m, d in METHODS.items()}
    baseT = {m: method_block(base_sets["T"], m, d) for m, d in METHODS.items()}
    out = {"baseline": base, "scenarios": {}}
    fixed_by = defaultdict(dict)    # method -> scenario -> P rows
    for name, pred in SCENARIOS.items():
        flips = scenario_flips(hr, pred)
        rows, matched = build_rows(W, flips)
        missing = sorted(flips - set(matched))
        if missing:
            raise SystemExit(f"ABORT: {name}: {len(missing)} harm pairs not found among accepted supports: {missing[:3]}")
        assert all(not u["correct"] for us in matched.values() for u in us), name
        sets = decisive_sets(rows)
        sc = {"pairs_flipped": len(flips), "support_records_flipped": sum(len(u) for u in matched.values()),
              "items_touched": len({k[0] for k in flips}), "methods": {}}
        for m, d in METHODS.items():
            nb = method_block(sets["P"], m, d)
            assert method_block(sets["T"], m, d)["c_vs_MAJ_items"] == baseT[m]["c_vs_MAJ_items"]
            sc["methods"][m] = {"acc": nb["acc"], "b_vs_MAJ": nb["b_vs_MAJ"], "c_vs_MAJ": nb["c_vs_MAJ"],
                                "c_D": nb["c_D"], "H3a_cp_upper_97_5": nb["overturn_of_right_majorities"]["cp_upper_97_5"],
                                "H3a_reject": nb["overturn_of_right_majorities"]["cp_upper_97_5"] < E.H3A_BOUND,
                                "F_items": sum(r["F"] for r in sets["P"]),
                                "vs_baseline": diff_block(base[m], nb)}
            fixed_by[m][name] = nb
        out["scenarios"][name] = sc
    # per-item split of the baseline harms
    cls_of_item = defaultdict(set)
    for h in hr:
        cls_of_item[h["item_id"]].add(h["cls"])
    split = {}
    for m in METHODS:
        b = base[m]
        items = sorted(set(b["c_vs_MAJ_items"]) | set(b["c_D_items"]))
        tab = []
        for iid in items:
            row = {"id": iid, "c_D": iid in b["c_D_items"], "c_vs_MAJ": iid in b["c_vs_MAJ_items"],
                   "classes_on_item": sorted(cls_of_item.get(iid, [])),
                   "fixed_by": [n for n in ("K", "E", "S", "G", "K+E", "K+E+S", "all (K+E+S+G)")
                                if iid not in fixed_by[m][n]["c_vs_MAJ_items"] and iid not in fixed_by[m][n]["c_D_items"]]}
            single = [n for n in ("K", "E", "S", "G") if n in row["fixed_by"]]
            row["attributed_to"] = (single[0] if len(single) == 1 else
                                    "+".join(single) + " (each alone)" if single else
                                    "joint" if row["fixed_by"] else "none (not a verified-wrong harm)")
            tab.append(row)
        split[m] = {"items": tab,
                    "c_D_by_class": dict(Counter(t["attributed_to"] for t in tab if t["c_D"])),
                    "c_vs_MAJ_by_class": dict(Counter(t["attributed_to"] for t in tab if t["c_vs_MAJ"]))}
    out["harm_split"] = split
    return out


# ── step 3 ──────────────────────────────────────────────────────

def judge_vs_F(P, hr):
    F_hr = {h["item_id"] for h in hr}
    F = {r["id"] for r in P if r["F"]}
    assert F == F_hr, (len(F), len(F_hr))
    out = {}
    for col in ("J", "J_nullwrong"):
        a = sum(1 for r in P if not r[col] and r["id"] in F)
        b = sum(1 for r in P if not r[col] and r["id"] not in F)
        c = sum(1 for r in P if r[col] and r["id"] in F)
        d = sum(1 for r in P if r[col] and r["id"] not in F)
        out[col] = {"table": {"J_wrong&F": a, "J_wrong&notF": b, "J_right&F": c, "J_right&notF": d},
                    "n": len(P), "J_wrong": a + b, "F": a + c,
                    "P(F | J wrong)": a / (a + b), "P(F | J right)": c / (c + d), **fisher_exact(a, b, c, d)}
    # by class of the F item (first of K, E, S, G)
    first = {}
    for h in hr:
        cur = first.get(h["item_id"])
        if cur is None or "KESG".index(h["cls"]) < "KESG".index(cur):
            first[h["item_id"]] = h["cls"]
    jw = {r["id"] for r in P if not r["J"]}
    out["J_wrong_by_F_class"] = {k: {"F_items": sum(1 for v in first.values() if v == k),
                                     "J_wrong": sum(1 for i, v in first.items() if v == k and i in jw)}
                                 for k in "KESG"}
    out["J_fallback_items_P"] = sum(r["J_fallback"] for r in P)
    return out


# ── step 4 population ───────────────────────────────────────────

def stability_population(sets, hr):
    """Pairs (check_key level) whose accepted `supports` label licensed a BE-G or VV decision that
    differs from MAJ or from the method's own default, on decisive P and T items; plus the 82
    supported-wrong pairs of harm_reading.jsonl. A pair licenses a decision when it is an accepted,
    status-ok citation, value-mapped to `supports`, by an agent proposing the decided value."""
    uses = defaultdict(list)
    for s, rs in sets.items():
        for r in rs:
            for m, dkey in (("BE-G", "D"), ("VV", "MAJ")):
                o = r[m + "_obj"]
                if o == r["MAJ_obj"] and o == r[dkey + "_obj"]:
                    continue
                kind = ("b" if r[m] and not r["MAJ"] else "c" if r["MAJ"] and not r[m] else "same_vs_MAJ")
                for p in r["_pairs"]:
                    if p["value"] == o and p["mapped_label"] == "supports":
                        uses[(r["id"], p["passage_key"], p["proposition_text"])].append(
                            dict(p, item_id=r["id"], set=s, source=r["source"], why=f"{m}:{kind}"))
    hk = {(h["item_id"], h["passage_key"], h["proposition"]) for h in hr}
    P_by = {r["id"]: r for r in sets["P"]}
    for (iid, pk, prop) in hk:
        for p in P_by[iid]["_pairs"]:
            if p["passage_key"] == pk and p["proposition_text"] == prop and p["mapped_label"] == "supports":
                uses[(iid, pk, prop)].append(dict(p, item_id=iid, set="P", source=P_by[iid]["source"],
                                                  why="supported_wrong"))
    assert hk <= set(uses)
    pairs = []
    for key in sorted(uses):
        us = uses[key]
        pairs.append({"item_id": key[0], "passage_key": key[1], "proposition_text": key[2],
                      "check_key": us[0]["check_key"], "label_map": us[0]["label_map"], "set": us[0]["set"],
                      "source": us[0]["source"], "value": us[0]["value"], "correct": us[0]["correct"],
                      "agents": sorted({u["agent"] for u in us}), "why": sorted({u["why"] for u in us})})
    checks = sorted({p["check_key"] for p in pairs})
    return pairs, checks


# ── main ────────────────────────────────────────────────────────

def main():
    W = World()
    hr = harm_pairs()
    rows, _ = build_rows(W, check_pub=True, keep_pairs=True)
    sets = decisive_sets(rows)
    # reproduction (same gate as selector_study)
    sel = json.load(open(V5 / "selector_study" / "results.json"))
    for m in METHODS:
        for s in ("P", "T"):
            got = method_block(sets[s], m, METHODS[m])
            want = sel["variants"][m][s]
            assert (got["acc"], got["b_vs_MAJ"], got["c_vs_MAJ"], got["c_D_items"]) == \
                (want["acc"], want["b_vs_MAJ"], want["c_vs_MAJ"], want["c_vs_D_items"]), (m, s)
    res = {"note": ("POST HOC, exploratory. Computed on the v5 confirmatory data after unblinding; nothing "
                    "here was preregistered. Label replay is a counterfactual on the sealed labels, not a new "
                    "measurement."),
           "evaluator_sha256": E.sha256_file(E.__file__), "accepted_checker": S.ACCEPTED, "config": S.CFG}
    res["step1_per_source"] = per_source(sets)
    res["step2_label_replay"] = attribution(W, sets, hr)
    res["step3_judge_vs_F"] = judge_vs_F(sets["P"], hr)
    pairs, checks = stability_population(sets, hr)
    n_k = 3
    res["step4_population"] = {
        "pairs": len(pairs), "distinct_check_keys": len(checks),
        "by_why": dict(Counter(w for p in pairs for w in p["why"])),
        "by_set": dict(Counter(p["set"] for p in pairs)),
        "licensing_only": sum(1 for p in pairs if "supported_wrong" not in p["why"]),
        "supported_wrong": sum(1 for p in pairs if "supported_wrong" in p["why"]),
        "k": n_k, "calls": n_k * len(checks), "usd_per_check": 0.0048,
        "estimated_usd": round(n_k * len(checks) * 0.0048, 2),
        "optional_original_rerun_calls": len(checks),
        "estimated_usd_with_original_rerun": round((n_k + 1) * len(checks) * 0.0048, 2)}
    with open(HERE / "stability_population.jsonl", "w") as f:
        for p in pairs:
            f.write(json.dumps(p, sort_keys=True) + "\n")
    with open(HERE / "results.json", "w") as f:
        json.dump(res, f, indent=1, sort_keys=True)
    print_tables(res)


def fmt(x, d=4):
    return "—" if x is None else f"{x:.{d}f}"


def print_tables(res):
    print("## Step 1")
    for m, by in res["step1_per_source"].items():
        print(f"\n### {m}\n")
        print("| set | source | n | MAJ acc | acc | b | c | c_D | n_R | c/n_R | Wilson 95% | CP 97.5% UB |")
        print("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for s, srcs in by.items():
            for src, o in srcs.items():
                q = o["overturn_of_right_majorities"]
                wl = q["wilson95"]
                print(f"| {s} | {src} | {o['n']} | {fmt(o['acc_MAJ'])} | {fmt(o['acc'])} | {o['b_vs_MAJ']} | "
                      f"{o['c_vs_MAJ']} | {o['c_D']} | {q['n_R']} | {fmt(q['rate'])} | "
                      f"{'—' if not wl else f'[{wl[0]:.4f}, {wl[1]:.4f}]'} | {fmt(q['cp_upper_97_5'])} |")
    print("\n## Step 2")
    st = res["step2_label_replay"]
    for m in METHODS:
        b = st["baseline"][m]
        print(f"\n### {m} (P)\n")
        print("| scenario | pairs | acc | Δacc | b | c vs MAJ | c_D | H3a UB | harms removed | corrections lost | new harms | new corr. |")
        print("|---|---|---|---|---|---|---|---|---|---|---|---|")
        print(f"| baseline | 0 | {fmt(b['acc'])} | — | {b['b_vs_MAJ']} | {b['c_vs_MAJ']} | {b['c_D']} | "
              f"{fmt(b['overturn_of_right_majorities']['cp_upper_97_5'])} | — | — | — | — |")
        for n, sc in st["scenarios"].items():
            o = sc["methods"][m]
            v = o["vs_baseline"]
            print(f"| {n} | {sc['pairs_flipped']} | {fmt(o['acc'])} | {v['d_acc']:+.4f} | {o['b_vs_MAJ']} | "
                  f"{o['c_vs_MAJ']} | {o['c_D']} | {fmt(o['H3a_cp_upper_97_5'])} | {len(v['harms_vs_MAJ_removed'])} | "
                  f"{len(v['corrections_lost'])} | {len(v['new_harms_vs_MAJ'])} | {len(v['new_corrections'])} |")
        sp = st["harm_split"][m]
        print(f"\nsplit c_D: {sp['c_D_by_class']}  c_vs_MAJ: {sp['c_vs_MAJ_by_class']}")
        for t in sp["items"]:
            print(f"  {t['id']:22} cD={int(t['c_D'])} cMAJ={int(t['c_vs_MAJ'])} cls={','.join(t['classes_on_item']) or '-':6} "
                  f"fixed_by={t['fixed_by']} -> {t['attributed_to']}")
    print("\n## Step 3")
    print(json.dumps(res["step3_judge_vs_F"], indent=1))
    print("\n## Step 4")
    print(json.dumps(res["step4_population"], indent=1))


if __name__ == "__main__":
    main()
