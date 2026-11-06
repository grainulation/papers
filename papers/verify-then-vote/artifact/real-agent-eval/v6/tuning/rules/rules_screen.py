#!/usr/bin/env python3
"""Exploratory screen: (A) discriminative support, (B) deterministic tie rule. Post hoc on v5; no model calls.
Imports the v5 selector_study reconstruction unmodified. Usage: python3 rules_screen.py (writes rules_results.json)."""
import json, random, sys
from collections import defaultdict
from pathlib import Path
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
V5 = HERE.parents[2] / "v5"
sys.path.insert(0, str(V5 / "selector_study"))
import selector_study as SS  # noqa
E = SS.E
PR = E.PR


def label_for(ctx, prop, pk):
    """('supports'|'other'|'unknown') for (default proposition, passage)."""
    ent = ctx.checks.get(PR.check_key(prop["proposition_key"], pk))
    if ent is None or ent["status"] != "ok" or ent["checker"]["checker_id"] not in ctx.accepted:
        return "unknown"
    return "supports" if PR.map_label(ent["label"], prop["label_map"]) == "supports" else "other"


def main():
    TWW, _, _ = SS.dev_trust_weights()
    ctx = SS.make_ctx(SS.CONF_DIR / "captures.jsonl", SS.CONF_DIR / "checks.jsonl")
    items = E.load_items(V5 / "benchmark" / "items_confirmatory.jsonl")
    raws = {f.stem: E.jload(f) for f in sorted((SS.CONF_DIR / "raw").glob("*.json"))}
    recs = []
    for iid in sorted(raws, key=lambda i: (items[i].get("order", 0), i)):
        rec = E.prepare_item(items[iid], raws[iid], ctx)
        row = rec["row"]
        row["set"] = E.analysis_set(rec["item"], strict=True)
        if not row["eligible"]:
            continue
        E.python_methods(rec, ctx, E.PREREG_BEST)
        if row["decisive"]:
            recs.append(rec)
    out = {}
    unk_needed = {"P": set(), "T": set()}
    unk_all = {"P": set(), "T": set()}
    R = {"P": [], "T": []}
    for rec in recs:
        row, s = rec["row"], rec["row"]["set"]
        if s not in R:
            continue
        iid = rec["item"]["id"]
        ver = [v for v in rec["parsed"] if E.supports_effective(v, ctx.accepted)]
        verv = {v["parsed"] for v in ver}
        inp = SS.gate_input(rec, ctx)
        mir = E.mirror(inp)
        if mir is None:
            Dv = rec["contribs"][0]["canonical_form"]["object"]
            tied = [Dv]
        else:
            P = SS.gate_parts(inp)
            d, _ = SS.sel(P["plural"], P["sc"])
            Dv = rec["by_id"][d]["parsed"]
            tied = None
        maj = row["MAJ_obj"]
        vals = [v["parsed"] for v in rec["parsed"]]
        _, tiedv = E._plurality(vals, "v5-majority:" + iid)
        cands = {}
        # (B) default variants
        cands["i"] = maj
        vt = [t for t in tiedv if t in verv]
        cands["ii"] = (Dv if (Dv in vt or not vt) and Dv in tiedv else (sorted(vt)[0] if vt else Dv)) if len(tiedv) > 1 else maj
        cands["iii"] = Dv if len(tiedv) > 1 and Dv in tiedv else maj
        r = {"id": iid, "set": s, "MAJ": row["MAJ"], "D": E.object_correct(rec, Dv)[0], "tied": len(tiedv) > 1,
             "ties": tiedv, "Dv": Dv}

        def vdf(default, restrict=None):
            """VV/VDF with given default; restrict = optional allowed verified values (rule A)."""
            if any(v["parsed"] == default for v in ver):
                return default
            vv = [v for v in ver if restrict is None or v["parsed"] in restrict]
            return E._plurality([v["parsed"] for v in vv], "v5-vv:" + iid)[0] if vv else default

        def allowed(default):
            """Rule A: verified values with a witnessing passage not labelled supports for the default's proposition."""
            prop = next(v["prop"] for v in rec["parsed"] if v["parsed"] == default)
            ok, unk_needed_here, unk_here = set(), set(), set()
            ok_u = set()
            for val in verv:
                wp = {a["passage_key"] for v in ver if v["parsed"] == val for a in v["audit"]
                      if a.get("support_label") == "supports" and a.get("support_status") == "ok" and a.get("accepted")}
                labs = {p: label_for(ctx, prop, p) for p in wp}
                if any(l == "other" for l in labs.values()):
                    ok.add(val); ok_u.add(val)
                elif any(l == "unknown" for l in labs.values()):
                    ok_u.add(val)  # passes only if unknown treated as not-supports
                    unk_needed_here |= {(prop["proposition_key"], p) for p, l in labs.items() if l == "unknown"}
                if any(l == "unknown" for l in labs.values()):
                    unk_here |= {(prop["proposition_key"], p) for p, l in labs.items() if l == "unknown"}
            return ok, ok_u, unk_needed_here, unk_here

        for k in ("i", "ii", "iii"):
            dflt = cands[k]
            r[f"B{k}_obj"] = vdf(dflt)
        # A on default MAJ (VV/VDF) and BE-G/VDF
        res = {}
        okA, okU, need, allu = allowed(maj)
        base = vdf(maj)
        overturn_base = base != maj
        res["VV_A_strict"] = vdf(maj, okA)         # unknown = not supports (more permissive)
        res["VV_A_lenient"] = vdf(maj, {v for v in verv if v in okA})  # unknown = supports (only known non-supports pass)
        # fix: strict = unknown counts as not-supports -> passes (okU); lenient = unknown counts as supports -> ok only
        res["VV_A_strict"] = vdf(maj, okU)
        res["VV_A_lenient"] = vdf(maj, okA)
        if overturn_base:
            unk_all[s] |= allu
            # needed only when overturn would flip on the unknown: values passing only via unknown
            if (okU - okA):
                unk_needed[s] |= need
        # BE-G/VDF
        if mir is None:
            bg_base = Dv
            res["BG_A_strict"] = res["BG_A_lenient"] = Dv
        else:
            Wv = {E.norm_obj(v["parsed"]) for v in ver}
            Wval = {v["parsed"] for v in ver}
            dn = E.norm_obj(Dv)
            if dn in Wv or not Wv:
                bg_base = Dv
                res["BG_A_strict"] = res["BG_A_lenient"] = Dv
            else:
                oD, oU, nd, au = allowed(Dv)
                def pick(allow):
                    W2 = {E.norm_obj(x) for x in allow}
                    return rec["by_id"][SS.sel(SS.members_of(P, W2), P["sc"])[0]]["parsed"] if W2 else Dv
                bg_base = rec["by_id"][SS.sel(SS.members_of(P, Wv), P["sc"])[0]]["parsed"]
                res["BG_A_strict"], res["BG_A_lenient"] = pick(oU), pick(oD)
                unk_all[s] |= au
                if oU - oD:
                    unk_needed[s] |= nd
        r["BG_base_obj"] = bg_base
        for k, o in res.items():
            r[k + "_obj"] = o
        r["VV_base_obj"] = base
        for k in list(r):
            if k.endswith("_obj") and k not in ("MAJ_obj",):
                r[k[:-4]] = E.object_correct(rec, r[k])[0]
        R[s].append(r)
    # tables
    def stats(rows, m, ref):
        n = len(rows)
        right = [r for r in rows if r["MAJ"]]
        c = sum(1 for r in right if not r[m])
        ub = E.cp_upper(c, len(right), E.H3A_ALPHA)
        b = sum(1 for r in rows if r[m] and not r["MAJ"])
        cc = sum(1 for r in rows if not r[m] and r["MAJ"])
        return {"acc": sum(r[m] for r in rows) / n, "b": b, "c": cc, "c_D": sum(1 for r in rows if r["D"] and not r[m]),
                "H3a_c": c, "H3a_UB": ub, "H3a_rej": ub < E.H3A_BOUND,
                "corr_lost": sum(1 for r in rows if r[ref] and not r[m] and not r["MAJ"]),
                "harms_removed": sum(1 for r in rows if (not r[ref]) and r[m] and r["MAJ"]) if False else
                                 sum(1 for r in rows if r["MAJ"] and not r[ref] and r[m]),
                "new_harms": sum(1 for r in rows if r["MAJ"] and r[ref] and not r[m]),
                "new_corr": sum(1 for r in rows if r[m] and not r[ref] and not r["MAJ"])}
    res = {}
    for s, rows in R.items():
        t = {}
        for m, ref in (("VV_base", "VV_base"), ("VV_A_strict", "VV_base"), ("VV_A_lenient", "VV_base"),
                       ("BG_base", "BG_base"), ("BG_A_strict", "BG_base"), ("BG_A_lenient", "BG_base"),
                       ("Bi", "Bi"), ("Bii", "Bi"), ("Biii", "Bi")):
            t[m] = stats(rows, m, ref)
        ties = [r for r in rows if r["tied"]]
        t["_ties"] = {"n_tied_items": len(ties),
                      "changed": {k: [r["id"] for r in ties if r[f"B{k}_obj"] != r["Bi_obj"]] for k in ("ii", "iii")},
                      "MAJ_correct_among_ties": sum(r["MAJ"] for r in ties)}
        # harm vs own default (default correct, output wrong)
        for k in ("i", "ii", "iii"):
            t[f"B{k}_harm_vs_own_default"] = None
        res[s] = t
    json.dump({"unknown_pairs_needed_P": len(unk_needed["P"]), "unknown_pairs_needed_T": len(unk_needed["T"]),
               "unknown_pairs_all_overturn_items_P": len(unk_all["P"]), "unknown_pairs_all_overturn_items_T": len(unk_all["T"]),
               "stats": res, "rows_P": R["P"]}, open(HERE / "rules_results.json", "w"), indent=1, default=str)
    print("unknown needed P/T:", len(unk_needed["P"]), len(unk_needed["T"]), "all:", len(unk_all["P"]), len(unk_all["T"]))
    for s in R:
        print(s, len(R[s]))
        for m, v in res[s].items():
            if not m.startswith("_") and isinstance(v, dict):
                print(f"{m:14}", {k: (round(x, 4) if isinstance(x, float) else x) for k, x in v.items()})
        print(res[s]["_ties"])


if __name__ == "__main__":
    main()
