#!/usr/bin/env python3
"""
Eval v6: rule `vdf-1` ("verified default first", PREREGISTRATION.md section 5.2) and the F1 analysis.

Loads the frozen v5 evaluator by path and changes nothing in it. For every eligible item it rebuilds
the item with `evaluate_v5.prepare_item`, takes W (the values with a witness) from
`evaluate_v5.supports_effective`, takes the reducer's default D and the BE-G winner from
`evaluate_v5.mirror`, and applies

    VV/VDF   = MAJ if MAJ in W, else VV (plurality over W, ties Random("v5-vv:"+id)), MAJ if W is empty
    BE-G/VDF = D   if D in W,   else BE-G (= sel(W)),                                 D if W is empty

MAJ, VV, D and BE-G are cross-checked against the evaluator's paired_decisions_v5.csv. No model call,
no hosted call, and the Rust binary is not run.

Outputs (evaluation_v6_vdf.json next to --out, plus a per-item csv):
  F1  H1a-VDF (exact two-sided McNemar, alpha 0.05) then, only if it rejects with b > c, H3a-VDF
      (one-sided 97.5% Clopper-Pearson upper bound < 0.05); the same two tests without the 15 v5
      design-set items; the VDF H4 rows; secondary BE-G/VDF (H1a and H3a forms); VV/VDF on T (H3b form).

Usage
  vdf_v6.py --eval-dir D --raw-dir R --captures C --checks K --items I --out O.json
  vdf_v6.py --reproduce-v5 ... --expect v5/selector_study/results.json   (the binding gate, section 5.2)
"""
import argparse
import csv
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True
V6 = Path(__file__).resolve().parent
V5 = V6.parent / "v5"
ROOT = V6.parents[1]


def load_v5(modname, fname):
    """Load a frozen v5 module by path, once per process (shared through sys.modules). No bytecode is written."""
    if modname in sys.modules:
        return sys.modules[modname]
    spec = importlib.util.spec_from_file_location(modname, V5 / fname)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


E = load_v5("evaluate_v5", "evaluate_v5.py")

CFG = E.PREREG_CONFIGS["BE-G"]                      # member/nei0.5/gated
H1_ALPHA = E.H1_ALPHA                               # 0.05, F1 step 1 (not Holm)
H3A_ALPHA, H3A_BOUND = E.H3A_ALPHA, E.H3A_BOUND     # one-sided 0.025, ceiling 0.05
VV_VDF, BG_VDF = "VV/VDF", "BE-G/VDF"

# the 15 v5 design-set items (prereg 2.1); sha256 of "\n".join(sorted(ids)) + "\n"
DESIGN_SET = sorted("""v5-fever80417 v5-fever90151 v5-popqa145561 v5-popqa175943 v5-popqa2211064 v5-popqa2342806
v5-popqa276747 v5-popqa2797971 v5-popqa4686489 v5-popqa6297573 v5-popqa6297574 v5-popqa695490 v5-scifactdev692
v5-scifactdev770 v5-scifactdev808""".split())
DESIGN_SET_SHA256 = "b675a5e67267d695f3dd93fd18dae360e1d1491cf56b7c4835061b1930fe3832"


def design_set_sha256():
    return hashlib.sha256(("\n".join(sorted(DESIGN_SET)) + "\n").encode()).hexdigest()


# ── the rule (pure; unit-tested branch by branch) ───────────────

def verified_values(parsed, accepted):
    """W: canonical values (norm_obj) with at least one accepted, status-ok, mapped `supports` label."""
    return {E.norm_obj(v["parsed"]) for v in parsed if E.supports_effective(v, accepted)}


def vdf_decide(parsed, item_id, d_obj, bg_obj, accepted):
    """Rule vdf-1 on one eligible item.

    parsed: the item's parsed responses (dicts with `parsed` = canonical answer and `audit`).
    d_obj / bg_obj: the reducer's default D and the BE-G winner (None when the item has no reducer slot,
    i.e. a single distinct value; both are then the only value).
    Returns MAJ, VV, W, the two VDF values and the branch each took."""
    maj, tied = E._plurality([v["parsed"] for v in parsed], "v5-majority:" + item_id)
    ver = [v for v in parsed if E.supports_effective(v, accepted)]
    W = {E.norm_obj(v["parsed"]) for v in ver}
    vv_tied = False
    if ver:
        vv, vv_t = E._plurality([v["parsed"] for v in ver], "v5-vv:" + item_id)
        vv_tied = len(vv_t) > 1
    else:
        vv = maj
    if d_obj is None:
        d_obj = bg_obj = maj
    # VV/VDF
    if E.norm_obj(maj) in W:
        vv_vdf, vv_branch = maj, "maj_verified"
    elif W:
        vv_vdf, vv_branch = vv, "vv_over_verified_tied" if vv_tied else "vv_over_verified"
    else:
        vv_vdf, vv_branch = maj, "w_empty"
    # BE-G/VDF
    if E.norm_obj(d_obj) in W:
        bg_vdf, bg_branch = d_obj, "d_verified"
    elif W:
        bg_vdf, bg_branch = bg_obj, "begg_over_verified"
    else:
        bg_vdf, bg_branch = d_obj, "w_empty"
    return {"MAJ": maj, "majority_tied": len(tied) > 1, "VV": vv, "W": sorted(W), "D": d_obj, "BE-G": bg_obj,
            VV_VDF: vv_vdf, BG_VDF: bg_vdf, "VV_VDF_branch": vv_branch, "BG_VDF_branch": bg_branch,
            "vv_tied": vv_tied}


# ── rebuilding items (as selector_study.py / evaluate_v5.reduce_method) ──

def make_ctx(captures, checks, accepted=None, ctx_strict=True):
    """ctx_strict mirrors evaluate_v5's --strict (abort on a missing capture or check); the reproduction runs strict."""
    args = SimpleNamespace(strict=ctx_strict)
    return E.Ctx(args, E.load_captures(captures), E.load_checks(checks), {}, accepted=accepted or [E.PREREG_CHECKER])


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


def mirror_objects(rec, ctx):
    """(D, BE-G winner) as canonical values from the evaluator's mirror of the frozen binary; (None, None) if no slot."""
    mir = E.mirror(gate_input(rec, ctx))
    if mir is None:
        return None, None
    by = rec["by_id"]
    return by[mir["gate"]["default_winner"]]["parsed"], by[mir["winner"]]["parsed"]


INT_COLS = ("decisive", "disagreement", "majority_tied", "MAJ", "VV", "D", "BE-G", "J", "RS", "CB-S", "ORC", "F", "fhat_pairs",
            "BE-G-L", "D-L", "VV-L", "F_L")
VV_VDF_L = "VV/VDF-L"
MINICHECK_ID = "98751cc07911d57a1586848dfb8c4e7b"


def read_paired(path):
    rows = {}
    for r in csv.DictReader(open(path, newline="")):
        rows[r["id"]] = r
    return rows


def build_rows(items_path, raw_dir, captures, checks, eval_dir, strict=True, accepted=None, ctx_strict=True,
               local_checks=None, local_accepted=None):
    """One row per eligible item: the CSV's published columns, plus the recomputed values and VDF columns.
    Aborts if MAJ, VV, D or BE-G recomputed here differ from paired_decisions_v5.csv. With local_checks (the MiniCheck
    labels) it also builds VV/VDF-L and cross-checks VV-L, D-L, BE-G-L and F_L against the evaluator's local columns."""
    ctx = make_ctx(captures, checks, accepted, ctx_strict)
    ctx_l = make_ctx(captures, local_checks, [local_accepted], ctx_strict) if local_checks else None
    items = E.load_items(items_path)
    raws = {f.stem: E.jload(f) for f in sorted(Path(raw_dir).glob("*.json"))}
    pub = read_paired(Path(eval_dir) / "paired_decisions_v5.csv")
    rows, mism = [], []
    for iid in sorted(raws, key=lambda i: (items[i].get("order", 0), i)):
        rec = E.prepare_item(items[iid], raws[iid], ctx)
        if not rec["row"]["eligible"]:
            continue
        p = pub.get(iid)
        if p is None:
            mism.append((iid, "missing from paired_decisions_v5.csv"))
            continue
        d_obj, bg_obj = mirror_objects(rec, ctx)
        dec = vdf_decide(rec["parsed"], iid, d_obj, bg_obj, ctx.accepted)
        ok = lambda o: E.object_correct(rec, o)[0]
        r = {k: (int(p[k]) if p.get(k, "") != "" else None) for k in INT_COLS if k in p}
        r.update({"id": iid, "source": p["source"], "set": E.analysis_set(rec["item"], strict=strict)})
        for col, val in (("MAJ", dec["MAJ"]), ("VV", dec["VV"]), ("D", dec["D"]), ("BE-G", dec["BE-G"])):
            if p[col + "_obj"] != str(val) or int(p[col]) != ok(val):
                mism.append((iid, col, val, ok(val), p[col + "_obj"], p[col]))
        if p["set"] != r["set"]:
            mism.append((iid, "set", r["set"], p["set"]))
        for m in (VV_VDF, BG_VDF):
            r[m], r[m + "_obj"] = ok(dec[m]), dec[m]
        r["W"] = dec["W"]
        r["VV_VDF_branch"], r["BG_VDF_branch"] = dec["VV_VDF_branch"], dec["BG_VDF_branch"]
        r["F"], r["fhat_pairs"] = E.f_and_pairs(rec, ctx.accepted)
        if p.get("F", "") != "" and int(p["F"]) != r["F"]:
            mism.append((iid, "F", r["F"], p["F"]))
        r["MAJ_obj"], r["D_obj"], r["VV_obj"], r["BE-G_obj"] = dec["MAJ"], dec["D"], dec["VV"], dec["BE-G"]
        if ctx_l:
            recl = E.prepare_item(items[iid], raws[iid], ctx_l)
            dl, bl = mirror_objects(recl, ctx_l)
            decl = vdf_decide(recl["parsed"], iid, dl, bl, ctx_l.accepted)
            okl = lambda o: E.object_correct(recl, o)[0]
            for col, val in (("VV-L", decl["VV"]), ("D-L", decl["D"]), ("BE-G-L", decl["BE-G"])):
                if int(p[col]) != okl(val):
                    mism.append((iid, col, val, okl(val), p[col]))
            if p["BE-G-L_obj"] != str(decl["BE-G"]):
                mism.append((iid, "BE-G-L_obj", decl["BE-G"], p["BE-G-L_obj"]))
            r["F_L"], r["fhat_pairs_L"] = E.f_and_pairs(recl, ctx_l.accepted)
            if int(p["F_L"]) != r["F_L"]:
                mism.append((iid, "F_L", r["F_L"], p["F_L"]))
            r[VV_VDF_L], r[VV_VDF_L + "_obj"] = okl(decl[VV_VDF]), decl[VV_VDF]
            r["VV_VDF_L_branch"], r["W_L"] = decl["VV_VDF_branch"], decl["W"]
            r["D-L_obj"] = decl["D"]
        rows.append(r)
    if mism:
        raise SystemExit(f"ABORT: vdf reconstruction differs from paired_decisions_v5.csv: {mism[:10]} ({len(mism)})")
    return rows


# ── analysis ────────────────────────────────────────────────────

def h3a_block(P, m):
    """The evaluator's H3a on P: c = #(m wrong) among items where MAJ is right; one-sided 97.5% CP bound < 0.05."""
    right = [r for r in P if r["MAJ"]]
    n_r = len(right)
    c = sum(1 for r in right if not r[m])
    ub = E.cp_upper(c, n_r, H3A_ALPHA)
    cmax = -1
    while n_r and E.cp_upper(cmax + 1, n_r, H3A_ALPHA) < H3A_BOUND:
        cmax += 1
    return {"set": "P", "method": m, "n_R": n_r, "c": c, "q_r": c / n_r if n_r else None, "cp_upper_97_5": ub,
            "bound": H3A_BOUND, "one_sided_alpha": H3A_ALPHA, "reject": bool(ub is not None and ub < H3A_BOUND),
            "c_max_that_rejects": cmax if cmax >= 0 else None}


def h1a_block(P, m, nb, seed):
    t = E._test(P, m, "MAJ", nb, seed)
    t["contrast"] = f"{m} vs MAJ on P"
    t["alpha"] = H1_ALPHA
    t["reject"] = bool(t["p_exact_mcnemar"] <= H1_ALPHA)
    t["reading"] = "not rejected" if not t["reject"] else "better" if t["b"] > t["c"] else "worse"
    return t


def h3b_block(T, m, nb, seed):
    pr = E._test(T, m, "MAJ", nb, seed)
    lo = pr["newcombe_ci95"][0] if pr["newcombe_ci95"] else None
    rej = bool(lo is not None and lo > E.H3B_MARGIN)
    return {"set": "T", **pr, "margin": E.H3B_MARGIN, "one_sided_alpha": 0.025, "newcombe_lower": lo, "reject": rej,
            "reading": "non-inferior" if rej else "not shown; point estimate negative" if (pr["diff"] or 0) < 0 else "not shown"}


def f1_sequence(P, m, nb, seed):
    """Fixed sequence (prereg 2.1): H3a runs only if H1a rejects with b > c."""
    h1 = h1a_block(P, m, nb, seed)
    go = bool(h1["reject"] and h1["b"] > h1["c"])
    h3 = h3a_block(P, m)
    h3["tested"] = go
    if not go:
        h3["reject"] = None
        h3["reading"] = "not tested (sequence stopped)"
    else:
        h3["reading"] = "harm below 5% shown" if h3["reject"] else "harm below 5% not shown"
    return {"H1a": h1, "H3a": h3, "sequence_completed": bool(go and h3["reject"])}


def analyse(rows, nb=10000, seed=42, avail=None, rate=None):
    dec = [r for r in rows if r["decisive"]]
    P = [r for r in dec if r["set"] == "P"]
    T = [r for r in dec if r["set"] == "T"]
    out = {"rule": "vdf-1", "n_eligible": len(rows), "n_decisive": len(dec), "n_P": len(P), "n_T": len(T)}
    out["F1"] = f1_sequence(P, VV_VDF, nb, seed)
    out["F1"]["reported_with"] = {"VV/VDF_overturn": E.overturn(P, VV_VDF), "accuracy_P": sum(r[VV_VDF] for r in P) / len(P) if P else None}
    # pre-declared sensitivity: P without the 15 design-set items
    ds = set(DESIGN_SET)
    Px = [r for r in P if r["id"] not in ds]
    out["F1_without_design_set"] = {"design_set_sha256": design_set_sha256(), "design_set_sha256_expected": DESIGN_SET_SHA256,
                                    "design_set_ids": DESIGN_SET, "n_in_P_decisive": len(P) - len(Px), "n": len(Px),
                                    **f1_sequence(Px, VV_VDF, nb, seed)}
    out["secondary"] = {
        BG_VDF: {"H1a_form": h1a_block(P, BG_VDF, nb, seed), "H3a_form": h3a_block(P, BG_VDF),
                 "H3b_form_T": h3b_block(T, BG_VDF, nb, seed)},
        "VV/VDF_on_T": h3b_block(T, VV_VDF, nb, seed)}
    # H4: VV/VDF is compared with MAJ (its default), BE-G/VDF with D
    out["H4"] = {"theorem": "c_D <= F; for VV/VDF the default is MAJ", "fhat_rate": rate}
    for s, rs in (("P", P), ("T", T)):
        out["H4"][s] = {VV_VDF: E.h4_block(rs, VV_VDF, "MAJ", "F", "fhat_pairs", rate),
                        BG_VDF: E.h4_block(rs, BG_VDF, "D", "F", "fhat_pairs", rate)}
    out["H4"]["harm_bound_holds"] = all(v["harm_bound_holds"] for s in ("P", "T") for v in out["H4"][s].values())
    out["H4"]["implementation_defect"] = not out["H4"]["harm_bound_holds"]
    # H5: accuracy, overturn and gap-closed for the two VDF methods
    out["accuracy"] = {s: {m: (sum(r[m] for r in rs) / len(rs) if rs else None)
                           for m in ("MAJ", "D", "VV", "BE-G", VV_VDF, BG_VDF)} for s, rs in (("P", P), ("T", T))}
    out["overturn_vs_MAJ"] = {s: {m: E.overturn(rs, m) for m in ("VV", "BE-G", VV_VDF, BG_VDF)} for s, rs in (("P", P), ("T", T))}
    refs = [x for x in ("J", "ORC") if (avail is None or avail.get(x)) and all(r.get(x) is not None for r in dec)]
    out["gap_closed"] = {s: E.gap_closed(rs, [VV_VDF, BG_VDF], refs, nb, seed) for s, rs in (("P", P), ("T", T))}
    if rows and VV_VDF_L in rows[0]:
        out["local_arm"] = analyse_local(rows, nb, seed, E.parse_rate(E.FHAT_RATE[E.PREREG_CHECKER]))
    out["branches"] = {s: {"VV/VDF": _count([r["VV_VDF_branch"] for r in rs]), "BE-G/VDF": _count([r["BG_VDF_branch"] for r in rs])}
                       for s, rs in (("P", P), ("T", T))}
    return out


def agreement(rows, a, b, s):
    """Decision agreement between two methods' selected values on the eligible items of set s: overall and on the
    disagreement items (>= 2 distinct values), Wilson 95% CIs, and the McNemar b/c between their correctness on the
    decisive conflicts of the set."""
    el = [r for r in rows if r["set"] == s]
    out = {}
    for name, rs in (("all_eligible", el), ("disagreement_items", [r for r in el if r.get("disagreement")])):
        k = sum(1 for r in rs if r[a + "_obj"] == r[b + "_obj"])
        out[name] = {"n": len(rs), "agree": k, "rate": k / len(rs) if rs else None, "wilson95": E.wilson(k, len(rs))}
    dec = [r for r in el if r["decisive"]]
    pr = E.paired(dec, a, b)
    out["decisive_paired"] = {k: pr[k] for k in ("n", "a", "b", "c", "d", "p_exact_mcnemar", "newcombe_ci95")}
    return out


def analyse_local(rows, nb=10000, seed=42, rate_l=None):
    """Secondary MiniCheck arm (prereg 2.5): H1a-L, H3a-L (reported whether or not H1a-L rejects), BE-G-L vs MAJ and its
    H3a form, agreement with hosted VV/VDF, and the H4 rows for both local methods."""
    dec = [r for r in rows if r["decisive"]]
    P = [r for r in dec if r["set"] == "P"]
    T = [r for r in dec if r["set"] == "T"]
    out = {"checker_id": MINICHECK_ID, "status": "secondary, unadjusted"}
    out["H1a_L"] = h1a_block(P, VV_VDF_L, nb, seed)
    out["H3a_L"] = h3a_block(P, VV_VDF_L)
    out["H3a_L"]["tested"] = True
    out["H3a_L"]["note"] = "reported whether or not H1a-L rejects"
    bgl = h1a_block(P, "BE-G-L", nb, seed)
    out["BE-G-L"] = {"H1a_form": bgl, "H3a_form": h3a_block(P, "BE-G-L")}
    out["VV/VDF-L_on_T"] = h3b_block(T, VV_VDF_L, nb, seed)
    out["agreement_with_hosted_VV/VDF"] = {s: agreement(rows, VV_VDF_L, VV_VDF, s) for s in ("P", "T")}
    out["H4"] = {"fhat_rate": rate_l}
    for s, rs in (("P", P), ("T", T)):
        out["H4"][s] = {VV_VDF_L: E.h4_block(rs, VV_VDF_L, "MAJ", "F_L", "fhat_pairs_L", rate_l),
                        "BE-G-L": E.h4_block(rs, "BE-G-L", "D-L", "F_L", "fhat_pairs_L", rate_l)}
    out["H4"]["harm_bound_holds"] = all(v["harm_bound_holds"] for s in ("P", "T") for v in out["H4"][s].values())
    out["accuracy"] = {s: {m: (sum(r[m] for r in rs) / len(rs) if rs else None) for m in ("MAJ", "VV-L", "BE-G-L", VV_VDF_L)}
                       for s, rs in (("P", P), ("T", T))}
    return out


def _count(xs):
    d = {}
    for x in xs:
        d[x] = d.get(x, 0) + 1
    return dict(sorted(d.items()))


def write_rows(rows, path):
    cols = ["id", "set", "source", "decisive", "majority_tied", "MAJ", "VV", "D", "BE-G", VV_VDF, BG_VDF, "F", "fhat_pairs",
            "MAJ_obj", "VV_obj", "D_obj", "BE-G_obj", VV_VDF + "_obj", BG_VDF + "_obj", "VV_VDF_branch", "BG_VDF_branch", "W"]
    if rows and VV_VDF_L in rows[0]:
        cols += ["BE-G-L", "D-L", "F_L", VV_VDF_L, VV_VDF_L + "_obj", "D-L_obj", "VV_VDF_L_branch"]
    flat = [dict(r, W="|".join(r["W"])) for r in rows]
    E.write_csv(path, flat, cols)


def run(items, raw_dir, captures, checks, eval_dir, out, bootstrap=10000, seed=42, strict=True, accepted=None,
        ctx_strict=True, local_checks=None, local_accepted=None):
    """Called by evaluate_v6.py (and the CLI). Reads the evaluator's outputs in eval_dir, writes `out` (json) and
    a per-item csv beside it, and returns the result dict."""
    rows = build_rows(items, raw_dir, captures, checks, eval_dir, strict, accepted, ctx_strict, local_checks, local_accepted)
    ev = E.jload(Path(eval_dir) / "evaluation_v5.json")
    pr = ev.get("prereg", {})
    rate = E.parse_rate(E.FHAT_RATE[E.PREREG_CHECKER])
    res = analyse(rows, bootstrap, seed, pr.get("available"), rate)
    res["evaluator"] = {"path": "real-agent-eval/v5/evaluate_v5.py", "sha256": E.sha256_file(E.__file__)}
    res["accepted_checker"] = accepted or [E.PREREG_CHECKER]
    res["config"] = CFG
    res["inputs"] = {"eval_dir": str(eval_dir), "items_sha256": E.sha256_file(items),
                     "paired_decisions_sha256": E.sha256_file(Path(eval_dir) / "paired_decisions_v5.csv")}
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(res, f, indent=2, sort_keys=True)
    write_rows(rows, out.with_name(out.stem + "_items.csv"))
    return res, rows


# ── reproduction gate (prereg 5.2) ──────────────────────────────

def summarize(rows, m, dkey):
    """selector_study.summarize, for the fields results.json stores."""
    ov = E.overturn(rows, m)
    cD = sorted(r["id"] for r in rows if r[dkey] and not r[m])
    F_items = {r["id"] for r in rows if r["F"]}
    return {"n": len(rows), "acc": sum(r[m] for r in rows) / len(rows), "b_vs_MAJ": ov["b"], "c_vs_MAJ": ov["c"],
            "net_vs_MAJ": ov["b"] - ov["c"], "p_exact_mcnemar_vs_MAJ": E.mcnemar_p(ov["b"], ov["c"]),
            "default": dkey, "b_vs_D": sum(1 for r in rows if r[m] and not r[dkey]), "c_vs_D": len(cD), "c_vs_D_items": cD,
            "c_vs_scoredD": sum(1 for r in rows if r["D"] and not r[m]),
            "c_vs_MAJ_items": sorted(r["id"] for r in rows if r["MAJ"] and not r[m]),
            "b_vs_MAJ_items": sorted(r["id"] for r in rows if r[m] and not r["MAJ"]),
            "F": len(F_items), "harm_bound_holds": set(cD) <= F_items}


def reproduce(rows, expect_path):
    """Compare VV/VDF and BE-G/VDF on P and T with selector_study/results.json, per item and in aggregate."""
    exp = E.jload(expect_path)["variants"]
    dec = [r for r in rows if r["decisive"]]
    sets = {s: [r for r in dec if r["set"] == s] for s in ("P", "T")}
    checks, bad = [], []
    for m, dkey in ((VV_VDF, "MAJ"), (BG_VDF, "D")):
        for s, rs in sets.items():
            got, want = summarize(rs, m, dkey), exp[m][s]
            if s == "P":
                got["H3a"] = {k: v for k, v in h3a_block(rs, m).items() if k in ("n_R", "c", "q_r", "cp_upper_97_5", "bound", "reject")}
            for k, v in got.items():
                w = want.get(k)
                ok = (v == w)
                checks.append({"variant": m, "set": s, "field": k, "match": ok})
                if not ok:
                    bad.append({"variant": m, "set": s, "field": k, "got": v if not isinstance(v, list) else v[:6],
                                "expected": w if not isinstance(w, list) else w[:6]})
            # fields the study stored that we do not recompute must at least exist
    n_items = sum(1 for r in dec)
    headline = {f"{s}/{m}": {k: summarize(rs, m, d)[k] for k in ("acc", "b_vs_MAJ", "c_vs_MAJ", "c_vs_D")}
                for m, d in ((VV_VDF, "MAJ"), (BG_VDF, "D")) for s, rs in sets.items()}
    hp = {m: h3a_block(sets["P"], m)["cp_upper_97_5"] for m in (VV_VDF, BG_VDF)}
    return {"all_match": not bad, "n_field_checks": len(checks), "n_mismatches": len(bad), "mismatches": bad,
            "n_decisive": n_items, "headline": headline, "H3a_upper_bound_P": hp}


# ── cli ─────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(description="eval v6 verified-default-first (rule vdf-1)")
    ap.add_argument("--eval-dir", required=True, help="directory holding paired_decisions_v5.csv and evaluation_v5.json")
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--captures", required=True)
    ap.add_argument("--checks", required=True)
    ap.add_argument("--items", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--reproduce-v5", action="store_true", help="the section 5.2 gate: needs --expect")
    ap.add_argument("--expect", help="v5/selector_study/results.json")
    ap.add_argument("--bootstrap", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args(argv)
    fz = E.jload(V5 / "FREEZE.json")["sha256"]
    if fz.get("real-agent-eval/v5/evaluate_v5.py") != E.sha256_file(E.__file__):
        raise SystemExit("ABORT: evaluate_v5.py is not the frozen v5 file")
    if design_set_sha256() != DESIGN_SET_SHA256:
        raise SystemExit("ABORT: design-set id list does not hash to the preregistered value")
    if a.reproduce_v5 and not a.expect:
        ap.error("--reproduce-v5 needs --expect")
    res, rows = run(a.items, a.raw_dir, a.captures, a.checks, a.eval_dir, a.out, a.bootstrap, a.seed)
    if a.reproduce_v5:
        rep = reproduce(rows, a.expect)
        rep["expect"] = {"path": str(a.expect), "sha256": E.sha256_file(a.expect)}
        rep["rows_csv"] = str(Path(a.out).with_name(Path(a.out).stem + "_items.csv"))
        rep["note"] = ("local reproduction of the post-hoc selector study on v5 confirmatory data; no model, hosted or "
                       "binary call. Not a confirmatory result.")
        with open(a.out, "w") as f:
            json.dump({"reproduction": rep, "analysis_on_v5_data_descriptive_only": res}, f, indent=2, sort_keys=True)
        print(json.dumps({k: rep[k] for k in ("all_match", "n_field_checks", "n_mismatches", "headline", "H3a_upper_bound_P")}, indent=1))
        if not rep["all_match"]:
            print("MISMATCH", json.dumps(rep["mismatches"][:5]))
            return 1
        return 0
    f1 = res["F1"]
    print(json.dumps({"H1a_VDF": {k: f1["H1a"][k] for k in ("n", "b", "c", "p_exact_mcnemar", "reject", "reading")},
                      "H3a_VDF": {k: f1["H3a"][k] for k in ("n_R", "c", "cp_upper_97_5", "tested", "reject")}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
