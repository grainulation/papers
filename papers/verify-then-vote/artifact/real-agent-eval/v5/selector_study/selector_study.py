#!/usr/bin/env python3
"""
Post-hoc selector study on the v5 confirmatory data (exploratory; NOT confirmatory).

Imports the frozen evaluator (real-agent-eval/v5/evaluate_v5.py, unmodified) and rebuilds every
eligible item exactly as the evaluator does (prepare_item -> the BE-G reducer input of
reduce_method -> evaluate_v5.mirror, which the confirmatory run verified equal to the frozen Rust
binary on all 7,910 slots). No model or hosted call is made; the Rust binary is not run.

Step 1 reproduces the published per-item columns (paired_decisions_v5.csv: MAJ, VV, BE-G, D and
their objects) and the published prereg numbers; it aborts on any mismatch.
Steps 2-5 classify the harm cases and simulate alternative selectors with the evaluator's own
definitions (overturn(), h4_block()-style c_D, cp_upper() for H3a).

Trust weights for variant (d) are estimated on the v5 DEV split only (results/dev/raw, dev gold).

Usage: python3 selector_study.py   (writes results.json next to this file)
"""
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
V5 = HERE.parent
sys.path.insert(0, str(V5))
import evaluate_v5 as E  # noqa: E402  frozen evaluator, imported read-only

CONF_DIR = V5 / "results" / "conf"
DEV_DIR = V5 / "results" / "dev"
CFG = E.PREREG_CONFIGS["BE-G"]          # member/nei0.5/gated
ACCEPTED = [E.PREREG_CHECKER]


# ── rebuild ─────────────────────────────────────────────────────

def make_ctx(captures, checks):
    args = SimpleNamespace(strict=True)
    return E.Ctx(args, E.load_captures(captures), E.load_checks(checks), {}, accepted=ACCEPTED)


def gate_input(rec, ctx):
    """The exact BE-G reducer input built by evaluate_v5.reduce_method."""
    item = rec["item"]
    inp = {"intent": item["question"], "criteria": [],
           "calibration": {c["agent_id"]: E.CALIBRATION for c in rec["contribs"]},
           "policy": E.policy_for("BE", [c["canonical_form"]["object"] for c in rec["contribs"]], ctx.accepted, CFG),
           "contributions": rec["contribs"]}
    if rec["store"]["captures"]:
        inp["evidence_store"] = rec["store"]
    return inp


def gate_parts(inp):
    """evaluate_v5.mirror's scoring and gate quantities, exposed for alternative selectors.
    Copied from mirror() line for line up to the gate; asserted equal to mirror() by the caller."""
    pol = inp["policy"]
    contribs = sorted(inp["contributions"], key=lambda c: (c["seq"], c["id"]))
    store = inp.get("evidence_store") or {"captures": {}, "support": {}}
    epol = E.copy.deepcopy(E.EV_DEFAULT)
    epol.update(E.copy.deepcopy(pol["evidence"]))
    w, db = pol["weights"], pol["deadband_threshold"]
    mask, eps = pol.get("schulze_dims", 31), pol["schulze_dim_epsilon"]
    citers = defaultdict(set)
    for c in contribs:
        for e in c["evidence"]:
            _, _, _, key, elig, _ = E._factors(e, c, store, epol)
            if elig:
                citers[key].add(c["agent_id"])
    n, denom = len(contribs), max(len(contribs) - 1, 1)
    dims, fin, sq = {}, {}, {}
    for rank, c in enumerate(contribs):
        ev = 0.0
        for e in c["evidence"]:
            q, r, s, key, elig, _ = E._factors(e, c, store, epol)
            base = e["weight"] * E.TW[e["type"]] * q * r * s
            ev += base * (E._mult(len(citers.get(key, ())) or 1) if elig else 0.9)
        ev = min(max(ev, 0.0), 1.0) if c["evidence"] else 0.0
        conf = min(c["confidence"] * inp["calibration"].get(c["agent_id"], 0.5), 1.0)
        rec_ = rank / denom
        raw = w[0] * ev + w[1] * conf + w[2] * 1.0 + w[3] * rec_ + w[4] * 1.0
        fin[c["id"]] = raw * 1.0
        sq[c["id"]] = E.q_round(fin[c["id"]])
        dims[c["id"]] = [ev, conf, 1.0, rec_, 1.0]
    ids = [c["id"] for c in contribs]
    by_id = {c["id"]: c for c in contribs}
    sc = {"sq": sq, "fin": fin, "dims": dims, "by_id": by_id, "w": w, "db": db, "mask": mask, "eps": eps,
          "cm": pol.get("candidate_mode", {"mode": "member"})}
    obj = lambda i: E.norm_obj(by_id[i]["canonical_form"]["object"])
    groups = defaultdict(list)
    for i in ids:
        groups[obj(i)].append(i)
    nag = {k: len({by_id[i]["agent_id"] for i in m}) for k, m in groups.items()}
    top = max(nag.values())
    wit = sorted(i for i in ids if any(E._factors(e, by_id[i], store, epol)[5] is not None
                                       and E._factors(e, by_id[i], store, epol)[5][0] == "supports"
                                       for e in by_id[i]["evidence"]))
    plural = [i for i in ids if nag[obj(i)] == top]
    return {"ids": ids, "sc": sc, "obj": obj, "groups": groups, "wit": wit, "plural": plural, "db": db}


def sel(cands, sc):
    return E._select(cands, sc)


def members_of(P, values):
    return [i for v in sorted(values) for i in P["groups"][v]]


# ── trust weights (dev only) ────────────────────────────────────

def dev_trust_weights():
    items = E.load_items(V5 / "benchmark" / "items_dev.jsonl")
    cnt = defaultdict(lambda: [0, 0])
    n_items = 0
    for f in sorted((DEV_DIR / "raw").glob("*.json")):
        raw = E.jload(f)
        item = items[raw["id"]]
        n_items += 1
        for r in raw["responses"]:
            v = E.response_view(item, r)
            if v["parsed"] is None:
                continue
            cnt[v["agent"]][0 if v["correct"] else 1] += 1
    w = {a: (1 + c) / (2 + c + i) for a, (c, i) in sorted(cnt.items())}
    return w, {a: {"correct": c, "incorrect": i} for a, (c, i) in sorted(cnt.items())}, n_items


def weighted_plurality(values_agents, weights, seed):
    """argmax of the summed agent weights per value on the 10,000 scale; exact ties seeded (CONF-style)."""
    s = defaultdict(float)
    for val, agent in values_agents:
        s[val] += weights[agent]
    q = {o: E.q_round(x) for o, x in s.items()}
    tied = sorted(o for o in q if q[o] == max(q.values()))
    return (tied[0] if len(tied) == 1 else random.Random(seed).choice(tied)), tied


# ── per item ────────────────────────────────────────────────────

def decide(rec, ctx, TWW):
    item, row = rec["item"], rec["row"]
    iid = item["id"]
    inp = gate_input(rec, ctx)
    mir = E.mirror(inp)
    out = {"slot": mir is not None}
    if mir is None:      # < 2 distinct values: every method returns the single value
        o = rec["contribs"][0]["canonical_form"]["object"]
        return {k: o for k in VARIANTS}, {"slot": False}, DEFAULTS
    P = gate_parts(inp)
    sc, obj, db = P["sc"], P["obj"], P["db"]
    by = rec["by_id"]
    # witness structure per value
    wag = defaultdict(set)      # value -> witness agents
    wcit = defaultdict(set)     # value -> distinct passage keys with an accepted supports label
    for i in P["wit"]:
        wag[obj(i)].add(by[i]["agent"])
    for v in rec["parsed"]:
        for a in v["audit"]:
            if a.get("support_label") == "supports" and a.get("support_status") == "ok" and a.get("accepted"):
                wcit[E.norm_obj(v["parsed"])].add(a["passage_key"])
    assert set(wag) == set(wcit), iid
    W = set(wag)
    W2ag = {k for k in W if len(wag[k]) >= 2}
    W2cit = {k for k in W if len(wcit[k]) >= 2}

    # BE-G as published
    d, d_inb = sel(P["plural"], sc)
    dv = obj(d)
    if W:
        wsel, w_inb = sel(members_of(P, W), sc)
        bg = wsel
    else:
        wsel, w_inb, bg = None, False, d
    assert bg == mir["winner"] and (mir["gate"]["default_winner"] == d), iid
    assert (mir["in_deadband"] == (w_inb if W else d_inb)), iid
    ch = {}
    O = lambda i: by[i]["parsed"]
    ch["BE-G"] = O(bg)
    ch["D"] = O(d)
    # (VDF) verified default first
    ch["BE-G/VDF"] = O(d) if dv in W else (O(wsel) if W else O(d))
    # (a) >=2 witness agents / >=2 distinct supporting passages, gate with W redefined
    for tag, Wx in (("a2ag", W2ag), ("a2cit", W2cit)):
        ch[f"BE-G/{tag}"] = O(sel(members_of(P, Wx), sc)[0]) if Wx else O(d)
        # (b) VDF + (a): the default is kept if verified at all; overturning needs the stronger set
        ch[f"BE-G/VDF+{tag}"] = (O(d) if dv in W else O(sel(members_of(P, Wx), sc)[0]) if Wx else O(d))
    # (c) escalation -> keep default
    esc1 = bool(W and obj(bg) != dv and w_inb)
    ch["BE-G/esc"] = O(d) if esc1 else O(bg)
    esc2 = bool(W and obj(bg) != dv and sc["sq"][bg] - sc["sq"][d] < db)
    ch["BE-G/esc-margin"] = O(d) if esc2 else O(bg)
    vdf = d if dv in W else (wsel if W else d)
    esc3 = bool(obj(vdf) != dv and w_inb)
    ch["BE-G/VDF+esc"] = O(d) if esc3 else O(vdf)

    # plurality family (VV): D = MAJ (random tie-break, evaluator's _plurality)
    maj = row["MAJ_obj"]
    ver = [v for v in rec["parsed"] if E.supports_effective(v, ctx.accepted)]
    assert {E.norm_obj(v["parsed"]) for v in ver} == W, iid
    vv_seed = "v5-vv:" + iid
    vv_ch = E._plurality([v["parsed"] for v in ver], vv_seed) if ver else (maj, [maj])
    ch["VV"] = vv_ch[0]
    ch["VV/VDF"] = maj if any(v["parsed"] == maj for v in ver) else vv_ch[0]
    for tag, Wx in (("a2ag", W2ag), ("a2cit", W2cit)):
        vx = [v for v in ver if E.norm_obj(v["parsed"]) in Wx]
        px = E._plurality([v["parsed"] for v in vx], vv_seed)[0] if vx else maj
        ch[f"VV/{tag}"] = px
        ch[f"VV/VDF+{tag}"] = maj if any(v["parsed"] == maj for v in ver) else px
    esc_vv = bool(ver and vv_ch[0] != maj and len(vv_ch[1]) > 1)
    ch["VV/esc-tie"] = maj if esc_vv else vv_ch[0]

    # (d) trust-weighted plurality (dev weights)
    tw, tw_tied = weighted_plurality([(v["parsed"], v["agent"]) for v in rec["parsed"]], TWW, "v5-tw:" + iid)
    ch["TW"] = tw
    twv = weighted_plurality([(v["parsed"], v["agent"]) for v in ver], TWW, "v5-twv:" + iid)[0] if ver else tw
    ch["TW-gate"] = twv                                           # sel = trust-weighted plurality on W
    ch["TW-gate/VDF"] = tw if any(v["parsed"] == tw for v in ver) else twv
    ch["BE-G/twD"] = O(wsel) if W else tw                         # scored sel(W), D = TW
    ch["BE-G/twD+VDF"] = tw if E.norm_obj(tw) in W else (O(wsel) if W else tw)
    ch["BE-G/twD+VDF+esc"] = (tw if (E.norm_obj(tw) not in W and W and w_inb) else ch["BE-G/twD+VDF"])

    assert set(ch) == set(VARIANTS)
    defaults = DEFAULTS
    meta = {"slot": True, "W": {k: {"agents": sorted(wag[k]), "passages": len(wcit[k])} for k in sorted(W)},
            "D_obj": O(d), "D_in_W": dv in W, "MAJ_in_W": E.norm_obj(maj) in W,
            "D_select_in_deadband": bool(d_inb), "BE-G_final_in_deadband": bool(mir["in_deadband"]),
            "BE-G_stage": mir["gate"]["stage"], "BE-G_winner_score_q": sc["sq"][bg], "D_score_q": sc["sq"][d],
            "escalated": {"BE-G/esc": esc1, "BE-G/esc-margin": esc2, "BE-G/VDF+esc": esc3, "VV/esc-tie": esc_vv,
                          "BE-G/twD+VDF+esc": bool(E.norm_obj(tw) not in W and W and w_inb)},
            "TW_obj": tw, "TW_tied": len(tw_tied) > 1,
            "n_agents": {k: len({by[i]["agent"] for i in m}) for k, m in P["groups"].items()},
            "F_W": any(not E.object_correct(rec, o)[0] for o in {O(m) for k in W for m in P["groups"][k]}),
            "F_W2ag": any(not E.object_correct(rec, O(P["groups"][k][0]))[0] for k in W2ag),
            "F_W2cit": any(not E.object_correct(rec, O(P["groups"][k][0]))[0] for k in W2cit)}
    return ch, meta, defaults


VARIANTS = ["BE-G", "D", "BE-G/VDF", "BE-G/a2ag", "BE-G/VDF+a2ag", "BE-G/a2cit", "BE-G/VDF+a2cit",
            "BE-G/esc", "BE-G/esc-margin", "BE-G/VDF+esc",
            "VV", "VV/VDF", "VV/a2ag", "VV/VDF+a2ag", "VV/a2cit", "VV/VDF+a2cit", "VV/esc-tie",
            "TW", "TW-gate", "TW-gate/VDF", "BE-G/twD", "BE-G/twD+VDF", "BE-G/twD+VDF+esc"]
# the default each variant is compared with for c_D / b_D
DEFAULTS = {k: ("D" if (k == "BE-G" or k.startswith("BE-G/")) and "twD" not in k else
                "TW" if (k.startswith("TW-gate") or "twD" in k) else "MAJ") for k in VARIANTS}
# which verified-set definition bounds each variant's harm (Proposition gate-harm with that W)
F_DEF = {k: ("F_W2ag" if "a2ag" in k and "VDF" not in k else "F_W2cit" if "a2cit" in k and "VDF" not in k
             else None if k in ("D", "TW") else "F_W") for k in VARIANTS}
# for VDF+(a): an overturn needs the stronger set, so harm is bounded by the stronger F as well
for k in VARIANTS:
    if "VDF+a2ag" in k:
        F_DEF[k] = "F_W2ag"
    if "VDF+a2cit" in k:
        F_DEF[k] = "F_W2cit"


def h3a(rows, m):
    right = [r for r in rows if r["MAJ"]]
    n_r = len(right)
    c = sum(1 for r in right if not r[m])
    ub = E.cp_upper(c, n_r, E.H3A_ALPHA)
    return {"n_R": n_r, "c": c, "q_r": c / n_r, "cp_upper_97_5": ub, "bound": E.H3A_BOUND,
            "reject": bool(ub < E.H3A_BOUND)}


def summarize(rows, m, dkey, ref_rows=None):
    n = len(rows)
    ov = E.overturn(rows, m)
    cD = sorted(r["id"] for r in rows if r[dkey] and not r[m])
    bD = sum(1 for r in rows if r[m] and not r[dkey])
    fdef = F_DEF[m]
    out = {"n": n, "acc": sum(r[m] for r in rows) / n, "b_vs_MAJ": ov["b"], "c_vs_MAJ": ov["c"],
           "net_vs_MAJ": ov["b"] - ov["c"], "p_exact_mcnemar_vs_MAJ": E.mcnemar_p(ov["b"], ov["c"]),
           "default": dkey, "b_vs_D": bD, "c_vs_D": len(cD), "c_vs_D_items": cD,
           "c_vs_scoredD": sum(1 for r in rows if r["D"] and not r[m]),
           "c_vs_MAJ_items": sorted(r["id"] for r in rows if r["MAJ"] and not r[m]),
           "b_vs_MAJ_items": sorted(r["id"] for r in rows if r[m] and not r["MAJ"])}
    if fdef:
        F_items = {r["id"] for r in rows if r["_meta"].get(fdef)}
        out["F_def"] = fdef
        out["F"] = len(F_items)
        out["harm_bound_holds"] = set(cD) <= F_items
    esc = [r for r in rows if r["_meta"].get("escalated", {}).get(m)]
    if any(m in r["_meta"].get("escalated", {}) for r in rows):
        out["escalated"] = len(esc)
        out["escalation_rate"] = len(esc) / n
        out["escalated_items"] = sorted(r["id"] for r in esc)
        out["escalated_D_correct"] = sum(r[dkey] for r in esc)
    return out


def main():
    TWW, tw_counts, n_dev = dev_trust_weights()
    ctx = make_ctx(CONF_DIR / "captures.jsonl", CONF_DIR / "checks.jsonl")
    items = E.load_items(V5 / "benchmark" / "items_confirmatory.jsonl")
    raws = {f.stem: E.jload(f) for f in sorted((CONF_DIR / "raw").glob("*.json"))}
    pub = {r["id"]: r for r in csv.DictReader(open(CONF_DIR / "eval" / "paired_decisions_v5.csv"))}
    ev = json.load(open(CONF_DIR / "eval" / "evaluation_v5.json"))
    rows = []
    mism = []
    for iid in sorted(raws, key=lambda i: (items[i].get("order", 0), i)):
        rec = E.prepare_item(items[iid], raws[iid], ctx)
        row = rec["row"]
        row["set"] = E.analysis_set(rec["item"], strict=True)
        if not row["eligible"]:
            continue
        E.python_methods(rec, ctx, E.PREREG_BEST)
        ch, meta, defaults = decide(rec, ctx, TWW)
        p = pub[iid]
        r = {"id": iid, "set": row["set"], "source": row["source"], "decisive": row["decisive"],
             "MAJ": row["MAJ"], "MAJ_obj": row["MAJ_obj"], "majority_tied": row["majority_tied"],
             "BE_in_deadband_csv": int(p["BE_in_deadband"]), "_meta": meta}
        for k, o in ch.items():
            r[k] = E.object_correct(rec, o)[0]
            r[k + "_obj"] = o
        # reproduction checks against the published per-item columns
        for col in ("MAJ", "VV", "BE-G", "D"):
            if str(r[col]) != p[col] or str(r[col + "_obj"]) != p[col + "_obj"]:
                mism.append((iid, col, r[col], r[col + "_obj"], p[col], p[col + "_obj"]))
        if meta["slot"] and meta["BE-G_stage"] != p["BE-G_stage"]:
            mism.append((iid, "stage", meta["BE-G_stage"], p["BE-G_stage"]))
        r["_defaults"] = defaults
        rows.append(r)
    if mism:
        print("ABORT: reconstruction mismatch", mism[:10], len(mism))
        sys.exit(1)
    dec = [r for r in rows if r["decisive"]]
    sets = {s: [r for r in dec if r["set"] == s] for s in ("P", "T")}
    pr = ev["prereg"]

    # step 1: published numbers
    repro = {}
    for s, rs in sets.items():
        got = {"n": len(rs), "acc_BE-G": sum(r["BE-G"] for r in rs) / len(rs), "acc_VV": sum(r["VV"] for r in rs) / len(rs),
               "acc_MAJ": sum(r["MAJ"] for r in rs) / len(rs), "acc_D": sum(r["D"] for r in rs) / len(rs),
               "BE-G_b_c_vs_MAJ": [E.overturn(rs, "BE-G")[k] for k in ("b", "c")],
               "VV_b_c_vs_MAJ": [E.overturn(rs, "VV")[k] for k in ("b", "c")],
               "BE-G_c_D": sorted(r["id"] for r in rs if r["D"] and not r["BE-G"])}
        want = {"n": pr["H4"][s]["BE-G"]["n"], "acc_BE-G": pr["accuracy"][s]["decisive"]["BE-G"],
                "acc_VV": pr["accuracy"][s]["decisive"]["VV"], "acc_MAJ": pr["accuracy"][s]["decisive"]["MAJ"],
                "acc_D": pr["accuracy"][s]["decisive"]["D"],
                "BE-G_b_c_vs_MAJ": [pr["overturn_vs_MAJ"][s]["BE-G"][k] for k in ("b", "c")],
                "VV_b_c_vs_MAJ": [pr["overturn_vs_MAJ"][s]["VV"][k] for k in ("b", "c")],
                "BE-G_c_D": pr["H4"][s]["BE-G"]["c_D_items"]}
        if got != want:
            print("ABORT: published numbers not reproduced", s, got, want)
            sys.exit(1)
        repro[s] = got
    h = h3a(sets["P"], "BE-G")
    pa = pr["H3"]["H3a"]
    assert (h["n_R"], h["c"], h["cp_upper_97_5"]) == (pa["n_R"], pa["c"], pa["cp_upper_97_5"]), (h, pa)
    repro["P"]["H3a"] = h

    # step 2: harm cases
    harms = {}
    for s, rs in sets.items():
        lst = []
        for r in rs:
            kinds = [k for k, c in (("BE-G c_D", r["D"] and not r["BE-G"]), ("BE-G c_MAJ", r["MAJ"] and not r["BE-G"]),
                                    ("VV c_MAJ", r["MAJ"] and not r["VV"]), ("VV c_scoredD", r["D"] and not r["VV"])) if c]
            if not kinds:
                continue
            m = r["_meta"]
            lst.append({"id": r["id"], "kinds": kinds, "MAJ_obj": r["MAJ_obj"], "MAJ": r["MAJ"], "D_obj": m["D_obj"],
                        "D": r["D"], "BE-G_obj": r["BE-G_obj"], "BE-G": r["BE-G"], "VV_obj": r["VV_obj"], "VV": r["VV"],
                        "W": m["W"], "n_agents": m["n_agents"], "D_in_W": m["D_in_W"], "MAJ_in_W": m["MAJ_in_W"],
                        "majority_tied": r["majority_tied"], "BE-G_stage": m["BE-G_stage"],
                        "BE-G_final_in_deadband": m["BE-G_final_in_deadband"],
                        "D_select_in_deadband": m["D_select_in_deadband"],
                        "BE_in_deadband_csv(ungated BE)": r["BE_in_deadband_csv"],
                        "score_q_winner_minus_D": m["BE-G_winner_score_q"] - m["D_score_q"]})
        harms[s] = lst

    # steps 3-5: variants
    var = {}
    base_bg = {s: {"c_D": {r["id"] for r in rs if r["D"] and not r["BE-G"]},
                   "c_MAJ": {r["id"] for r in rs if r["MAJ"] and not r["BE-G"]},
                   "b_MAJ": {r["id"] for r in rs if r["BE-G"] and not r["MAJ"]}} for s, rs in sets.items()}
    base_vv = {s: {"c_MAJ": {r["id"] for r in rs if r["MAJ"] and not r["VV"]},
                   "b_MAJ": {r["id"] for r in rs if r["VV"] and not r["MAJ"]}} for s, rs in sets.items()}
    for m in VARIANTS:
        var[m] = {}
        for s, rs in sets.items():
            dkey = rs[0]["_defaults"][m]
            out = summarize(rs, m, dkey)
            ids_c, ids_b = set(out["c_vs_MAJ_items"]), set(out["b_vs_MAJ_items"])
            ref = base_vv[s] if m.startswith("VV") else base_bg[s]
            out["vs_reference"] = {"reference": "VV" if m.startswith("VV") else "BE-G",
                                   "ref_harms_vs_MAJ_removed": len(ref["c_MAJ"] - ids_c),
                                   "new_harms_vs_MAJ": sorted(ids_c - ref["c_MAJ"]),
                                   "ref_corrections_lost": len(ref["b_MAJ"] - ids_b),
                                   "new_corrections": len(ids_b - ref["b_MAJ"])}
            if not m.startswith("VV"):
                out["vs_reference"]["BE-G_c_D_items_still_wrong"] = sorted(i for i in base_bg[s]["c_D"]
                                                                          if not next(r for r in rs if r["id"] == i)[m])
            if s == "P":
                out["H3a"] = h3a(rs, m)
            var[m][s] = out
    res = {"note": ("POST HOC, exploratory. Computed on the v5 confirmatory data after unblinding; "
                    "none of these variants was preregistered. They can become confirmatory only through a new "
                    "preregistered run on fresh data."),
           "evaluator": {"path": "real-agent-eval/v5/evaluate_v5.py", "sha256": E.sha256_file(E.__file__)},
           "config": CFG, "accepted_checker": ACCEPTED,
           "trust_weights_dev": {"n_dev_items": n_dev, "counts": tw_counts, "weights": TWW,
                                 "formula": "posterior mean of Beta(1 + correct, 1 + incorrect), dev split only"},
           "reproduction": repro, "harm_cases": harms, "variants": var}
    with open(HERE / "results.json", "w") as f:
        json.dump(res, f, indent=1, sort_keys=True, default=lambda o: sorted(o) if isinstance(o, set) else str(o))
    # brief console table
    print("reproduced:", json.dumps({s: {k: v for k, v in repro[s].items() if k != "BE-G_c_D"} for s in repro}))
    hdr = f"{'variant':22} {'set':3} {'acc':>6} {'b':>4} {'c':>4} {'cD':>4} {'esc':>4} {'H3a_ub':>7} rej rm_harm lost_corr new_corr bound"
    print(hdr)
    for m in VARIANTS:
        for s in ("P", "T"):
            o = var[m][s]
            h3 = o.get("H3a", {})
            print(f"{m:22} {s:3} {o['acc']:.4f} {o['b_vs_MAJ']:4} {o['c_vs_MAJ']:4} {o['c_vs_D']:4} "
                  f"{o.get('escalated', ''):>4} {h3.get('cp_upper_97_5', 0):7.4f} {str(h3.get('reject', '')):3} "
                  f"{o['vs_reference']['ref_harms_vs_MAJ_removed']:7} {o['vs_reference']['ref_corrections_lost']:9} "
                  f"{o['vs_reference']['new_corrections']:8} {o.get('harm_bound_holds', '-')}")


if __name__ == "__main__":
    main()
