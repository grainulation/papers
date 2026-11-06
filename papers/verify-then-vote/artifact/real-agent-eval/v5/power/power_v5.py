#!/usr/bin/env python3
"""Eval v5 power analysis (v3/SWARM3_DESIGN.md §6; swarm-3 lane L7).

Reproduces every number in the design's §6:

  0. the v4 anchor: N = 207 decisive conflicts at psi = 0.25, Delta = 0.10 (v4 POWER.md Table 1),
     using the v4 functions unchanged (imported from ../../v4/power/power.py);
  1. §6.1 Stage A: majority accuracy on the v4 *dev* split, from
     ../../v4/results/dev/responses_v4.jsonl only (majority only; no Bran selection is read;
     ties count as the expectation of the seeded-random tie-break; an object is graded on its
     smallest-contribution-id member, as v4 evaluate_v4.object_correct);
  2. §6.2 table: N for 80% power of the exact two-sided McNemar test at alpha = 0.05, over
     (m, p_w, q_r) with b/N = m p_w, c/N = (1 - m) q_r, Delta = b/N - c/N, psi = b/N + c/N;
     N = smallest value with power >= 0.80 that stays there for 25 further values;
  3. planning: point (m .35, p_w .4, q_r .10) -> N = 302; Delta fixed at 0.075 with psi floored
     at 0.25 -> N* = 368 (and 294 / 438 at psi .20 / .30); items = N* / 0.45 ~ 820;
  4. the §6.2 stopping-rule function I = ceil(N*(psi_dev) / y_dev) clamped to [1000, 1400];
  5. the SciFact-only fallback (§2.2): N = 129 at psi = 0.35, Delta = 0.15 (v4 Table 1);
  6. H2 non-inferiority power (margin -0.05, one-sided 0.025, true difference 0), both by the
     normal approximation the design quotes and by v4's Monte Carlo Wald test.

It never reads ../../v4/results/conf/ (v4 confirmatory data are blinded).

Usage:  python3 power_v5.py [--quick]     (writes power_results_v5.json next to this file)
numpy only; deterministic (seed 20261022). --quick skips the slow > 1,500 cell.
"""
import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.normpath(os.path.join(HERE, "..", "..", "v4"))
sys.path.insert(0, os.path.join(V4, "power"))
import power as P4  # noqa: E402  v4 exact McNemar power (unchanged)

SEED = 20261022
QUICK = "--quick" in sys.argv
DEV_RESPONSES = os.path.join(V4, "results", "dev", "responses_v4.jsonl")
DELTA_PLAN = 0.075
PSI_FLOOR = 0.25
YIELD_PLAN = 0.45
ITEM_CLAMP = (1000, 1400)
UNREACHABLE = 0.02          # "—": Delta <= 0.02
NMAX_TABLE = 1500           # "> 1,500" beyond this
Z975 = 1.959963984540054

GRID = [  # (m, p_w) rows of the §6.2 table; columns q_r
    (0.35, 0.3), (0.35, 0.4), (0.35, 0.5), (0.25, 0.4), (0.25, 0.5)]
QR = (0.05, 0.10, 0.15)
DESIGN_TABLE = {  # as printed in §6.2 (None = "—", ">1500" = "> 1,500")
    (0.35, 0.3): (221, 872, None), (0.35, 0.4): (123, 302, 1070), (0.35, 0.5): (83, 165, 374),
    (0.25, 0.4): (293, ">1500", None), (0.25, 0.5): (179, 658, None)}


def b_c(m, pw, qr):
    b, c = m * pw, (1 - m) * qr
    return b - c, b + c


def n_star(psi, delta, nmax=4000):
    return P4.min_n_stable(psi, delta, nmax=nmax)


def stopping_rule(psi_dev, y_dev, delta=DELTA_PLAN):
    """§6.2: I = ceil(N*(max(psi_dev, 0.25)) / y_dev), clamped to [1000, 1400]."""
    psi = max(psi_dev, PSI_FLOOR)
    n = n_star(psi, delta)
    raw = math.ceil(n / y_dev) if y_dev > 0 else None
    i = ITEM_CLAMP[1] if raw is None else min(max(raw, ITEM_CLAMP[0]), ITEM_CLAMP[1])
    return {"psi_dev": psi_dev, "psi_used": psi, "delta": delta, "N_star": n, "y_dev": y_dev,
            "I_unclamped": raw, "I": i, "exceeds_cap": raw is None or raw > ITEM_CLAMP[1]}


def ni_power_normal(N, psi, margin=-0.05):
    """Normal approximation: d_hat ~ N(0, psi / N); reject if d_hat - z sqrt(psi/N) > margin."""
    se = math.sqrt(psi / N)
    return 0.5 * (1 + math.erf((-margin / se - Z975) / math.sqrt(2)))


# ── §6.1 Stage A (dev only) ─────────────────────────────────────

def stage_a(path=DEV_RESPONSES):
    if "results/conf" in path.replace(os.sep, "/"):
        raise SystemExit("refused: v4 confirmatory results are blinded")
    by = defaultdict(list)
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            by[r["id"]].append(r)
    keys = ["all", "truthfulqa", "popqa", "fever", "scifact"]
    t = {k: Counter() for k in keys}
    minority = Counter()
    for iid, rs in sorted(by.items()):
        src = rs[0]["source"]
        p = [r for r in rs if r["parsed"] is not None]
        if p and not any(r["gak_correct"] for r in p):
            for k in ("all", src):
                t[k]["all_wrong"] += 1
        if len(p) < 2:
            continue
        nc = sum(r["gak_correct"] for r in p)
        if not 0 < nc < len(p):
            continue
        cnt = Counter(r["parsed"] for r in p)
        top = max(cnt.values())
        tied = sorted(o for o, k in cnt.items() if k == top)

        def oc(o):
            h = sorted((r for r in p if r["parsed"] == o),
                       key=lambda r: hashlib.sha256(f"{iid}|{r['agent']}|answer|{o}".encode()).hexdigest()[:16])
            return h[0]["gak_correct"]
        e = sum(oc(o) for o in tied) / len(tied)
        strict_wrong = len(tied) == 1 and not oc(tied[0])
        for k in ("all", src):
            t[k]["decisive"] += 1
            t[k]["maj_correct_expected"] += e
            t[k]["ties_at_top"] += int(len(tied) > 1)
            t[k]["strict_wrong"] += int(strict_wrong)
            t[k]["ge3_on_one_wrong_value"] += int(any(k2 >= 3 and not oc(o) for o, k2 in cnt.items()))
        if strict_wrong:
            right = [r for r in p if r["gak_correct"]]
            if len(right) == 1:
                minority[right[0]["agent"]] += 1
            minority["_strict_wrong_items"] += 1
            minority["_single_agent_minority"] += int(len(right) == 1)
            minority["_minority_with_evidence"] += int(any(r["n_evidence"] > 0 for r in right))
    out = {}
    for k in keys:
        d = t[k]
        n = d["decisive"]
        mw = n - d["maj_correct_expected"]
        out[k] = {"decisive": n, "maj_correct_expected": round(d["maj_correct_expected"], 2),
                  "maj_wrong_expected": round(mw, 2), "m": round(mw / n, 4) if n else None,
                  "strict_wrong": d["strict_wrong"], "ties_at_top": d["ties_at_top"],
                  "ge3_on_one_wrong_value": d["ge3_on_one_wrong_value"], "all_wrong_items": d["all_wrong"]}
    out["n_items"] = len(by)
    out["strict_wrong_minority"] = dict(minority)
    with open(path, "rb") as fh:
        out["source_file_sha256"] = hashlib.sha256(fh.read()).hexdigest()
    return out


# ── main ────────────────────────────────────────────────────────

def main():
    rng = np.random.default_rng(SEED)
    res = {"seed": SEED, "quick": QUICK, "alpha": 0.05, "power_target": 0.80, "stability_window": 25,
           "v4_power_module_sha256": hashlib.sha256(open(P4.__file__, "rb").read()).hexdigest()}

    # 0. v4 anchor
    anchor = n_star(0.25, 0.10)
    res["v4_anchor"] = {"psi": 0.25, "delta": 0.10, "N": anchor, "expected": 207, "match": anchor == 207}
    assert anchor == 207, anchor

    # 1. Stage A
    res["stage_a"] = stage_a()
    m_stage_a = res["stage_a"]["all"]["m"]

    # 2. §6.2 table
    rows = []
    for m, pw in GRID:
        for j, qr in enumerate(QR):
            d, psi = b_c(m, pw, qr)
            cell = {"m": m, "p_w": pw, "q_r": qr, "b_over_N": round(m * pw, 6), "c_over_N": round((1 - m) * qr, 6),
                    "delta": round(d, 6), "psi": round(psi, 6)}
            if d <= UNREACHABLE:
                cell["N"] = None
                cell["note"] = "unreachable (Delta <= 0.02)"
            else:
                n = n_star(psi, d, nmax=NMAX_TABLE)
                if n is None:
                    cell["N"] = ">1500"
                    if not QUICK:
                        cell["N_exact_beyond_table"] = n_star(psi, d, nmax=8000)
                else:
                    cell["N"] = n
                    cell["exact_power_at_N"] = round(P4.exact_power(n, psi, d), 4)
                    cell["mc_power_at_N"] = round(P4.mc_power(n, psi, d, 4000 if QUICK else 20000, rng), 4)
            cell["design"] = DESIGN_TABLE[(m, pw)][j]
            cell["matches_design"] = cell["N"] == cell["design"]
            rows.append(cell)
    res["table_6_2"] = rows

    # 3. planning
    d_pt, psi_pt = b_c(0.35, 0.4, 0.10)
    plan = {"point": {"m": 0.35, "p_w": 0.4, "q_r": 0.10, "delta": round(d_pt, 6), "psi": round(psi_pt, 6),
                      "N": n_star(psi_pt, d_pt)},
            "N_star_delta_0075": {str(p): n_star(p, DELTA_PLAN) for p in (0.20, 0.25, 0.30)},
            "m_stage_a": m_stage_a}
    plan["N_star"] = plan["N_star_delta_0075"]["0.25"]
    plan["items_at_yield_0_45"] = math.ceil(plan["N_star"] / YIELD_PLAN)
    plan["items_at_yield_0_50"] = math.ceil(plan["N_star"] / 0.50)
    plan["power_at_N_star_point"] = round(P4.exact_power(plan["N_star"], psi_pt, d_pt), 4)
    plan["primary_items"] = 1000
    res["planning"] = plan

    # 4. stopping rule examples (the function evaluate_v5 imports)
    res["stopping_rule_examples"] = [stopping_rule(psi, y) for psi in (0.15, 0.25, 0.30, 0.40) for y in (0.30, 0.45, 0.60)]

    # 5. SciFact-only fallback
    res["scifact_only_fallback"] = {"fresh_items": 283, "yield": 0.42, "decisive_expected": round(283 * 0.42, 1),
                                    "N_delta_0_15_psi_0_35": n_star(0.35, 0.15), "design": 129,
                                    "N_delta_0_10_psi_0_35": n_star(0.35, 0.10)}

    # 6. H2 non-inferiority
    h2 = []
    for N in (368, 450):
        for psi in (0.15, 0.10):
            h2.append({"N": N, "psi_BE_J": psi, "margin": -0.05, "true_diff": 0.0,
                       "power_normal_approx": round(ni_power_normal(N, psi), 3),
                       "power_mc_wald_v4": round(P4.ni_power(N, psi, 0.0, margin=-0.05,
                                                             reps=4000 if QUICK else 20000, rng=rng), 3)})
    res["h2_noninferiority"] = h2

    out = os.path.join(HERE, "power_results_v5.json")
    with open(out, "w") as f:
        json.dump(res, f, indent=1, sort_keys=True)
    bad = [r for r in rows if not r["matches_design"]]
    print("wrote", out)
    print("v4 anchor N =", anchor)
    print("stage A all:", res["stage_a"]["all"])
    for r in rows:
        print(f"m={r['m']} p_w={r['p_w']} q_r={r['q_r']}: N={r['N']} (design {r['design']})"
              + (f" exact={r['N_exact_beyond_table']}" if "N_exact_beyond_table" in r else ""))
    print("planning:", {k: plan[k] for k in ("point", "N_star_delta_0075", "N_star", "items_at_yield_0_45")})
    print("scifact fallback:", res["scifact_only_fallback"])
    for h in h2:
        print("H2", h)
    print("table mismatches:", len(bad))
    return 0 if not bad and plan["point"]["N"] == 302 and plan["N_star"] == 368 else 1


if __name__ == "__main__":
    sys.exit(main())
