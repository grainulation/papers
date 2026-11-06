#!/usr/bin/env python3
"""
Eval v6 (pool replication) power: exact binomial / Clopper-Pearson, standard library only.

No data are read and no model is called. The only inputs are the v5 confirmatory H3a counts,
stated as constants below (real-agent-eval/v5/results/conf/RESULTS.md, H3 table):
c = 12 BE-G overturns of n_R = 376 right majorities on P.

Computes
  H3a (v6 alone)  reject iff the one-sided 97.5% Clopper-Pearson upper bound on c/n_R is < 0.05,
                  exactly as evaluate_v5.py `h3a` (same bisection). Power = P(Binom(n_R, q) <= c_max).
  H3a-pool (exact, secondary)
                  reject iff cp_upper(12 + c6, 376 + n6) < 0.05. Power = P(c6 <= c_max(376+n6) - 12).
  H3a-pool-robust (sensitivity, valid under any dependence between the two studies)
                  U = (376 * U5 + n6 * U6) / (376 + n6), each U_i a one-sided 98.75% CP bound
                  (Bonferroni split of 0.025); reject iff U < 0.05.
  Predictive pass probability: q ~ Beta(12.5, 364.5) (Jeffreys posterior from v5), then the above.
  H1a (v6 alone)  exact two-sided McNemar power, at alpha 0.025 (Holm first step) and 0.05.
  VV/VDF          (draft primary family F1) H3a at q = 4/376 (v5 post hoc), 0.02, 0.03; H1a at the
                  post hoc v5 effect (b = 87, c = 4 of N = 526) and at half of it (two readings);
                  a Bonferroni lower bound on the fixed sequence H1a -> H3a.

Usage: python3 -I real-agent-eval/v6/power/power_v6.py [--out power_results_v6.json]
Runs in a few seconds. Exits non-zero if the self-checks fail.
"""

import argparse
import json
import math
import sys
from pathlib import Path

H3A_BOUND, H3A_ALPHA = 0.05, 0.025
V5_C, V5_NR = 12, 376                      # v5 RESULTS.md H3a row (BE-G, P)
V5_DECISIVE_P, V5_B, V5_C_H1A = 526, 91, 12  # v5 RESULTS.md H1a row
Q_GRID = [V5_C / V5_NR, 0.025, 0.02, 1 / 60, 0.01]
NR_GRID = [300, 340, 376, 410, 450]
# VV/VDF, post hoc on v5 P (v5/selector_study/results.json): b = 87, c = 4 vs MAJ; H3a c = 4 of 376
VDF_B, VDF_C = 87, 4
VDF_Q_GRID = [VDF_C / V5_NR, 0.02, 0.03]


def binom_pmf(k, n, p):
    if p <= 0.0:
        return 1.0 if k == 0 else 0.0
    if p >= 1.0:
        return 1.0 if k == n else 0.0
    return math.exp(math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
                    + k * math.log(p) + (n - k) * math.log1p(-p))


def binom_cdf(k, n, p):
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    return min(1.0, sum(binom_pmf(i, n, p) for i in range(k + 1)))


def cp_upper(x, n, alpha=H3A_ALPHA):
    """Same definition and bisection as evaluate_v5.cp_upper."""
    if n == 0:
        return None
    if x >= n:
        return 1.0
    lo, hi = x / n, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if binom_cdf(x, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return hi


_CMAX = {}


def c_max(n, alpha=H3A_ALPHA, bound=H3A_BOUND):
    """Largest c with cp_upper(c, n) < bound, or -1."""
    key = (n, alpha, bound)
    if key not in _CMAX:
        c = -1
        while cp_upper(c + 1, n, alpha) < bound:
            c += 1
        _CMAX[key] = c
    return _CMAX[key]


def power_h3a(n, q):
    return binom_cdf(c_max(n), n, q)


def power_pool_exact(n6, q):
    return binom_cdf(c_max(V5_NR + n6) - V5_C, n6, q)


_U5 = None


def pool_robust_cmax(n6):
    """Largest c6 for which the dependence-robust pooled bound is < 0.05."""
    global _U5
    if _U5 is None:
        _U5 = cp_upper(V5_C, V5_NR, H3A_ALPHA / 2)
    c = -1
    while True:
        u6 = cp_upper(c + 1, n6, H3A_ALPHA / 2)
        if (V5_NR * _U5 + n6 * u6) / (V5_NR + n6) < H3A_BOUND:
            c += 1
        else:
            return c


def power_pool_robust(n6, q):
    return binom_cdf(pool_robust_cmax(n6), n6, q)


def beta_grid(a, b, m=4000):
    """Midpoint grid over (0, 0.2] for a Beta(a, b) density (mass beyond 0.2 is negligible here)."""
    hi = 0.2
    xs = [(i + 0.5) * hi / m for i in range(m)]
    lb = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    w = [math.exp((a - 1) * math.log(x) + (b - 1) * math.log1p(-x) - lb) * hi / m for x in xs]
    s = sum(w)
    return xs, [x / s for x in w], s


def predictive(fn, n):
    xs, ws, _ = beta_grid(V5_C + 0.5, V5_NR - V5_C + 0.5)
    # fn(n, q) is a step function of a cdf; evaluate on the grid
    return sum(w * fn(n, q) for q, w in zip(xs, ws))


def mcnemar_p(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


_REJ = {}


def rej_b_set(d, alpha):
    """b values (with b > c) that reject at alpha for d discordant pairs."""
    key = (d, alpha)
    if key not in _REJ:
        _REJ[key] = [b for b in range(d + 1) if b > d - b and mcnemar_p(b, d - b) <= alpha]
    return _REJ[key]


def power_mcnemar(N, psi, delta, alpha):
    """P(reject with b > c). b+c ~ Binom(N, psi); b | d ~ Binom(d, (psi + delta) / (2 psi))."""
    pb = (psi + delta) / (2 * psi)
    tot = 0.0
    for d in range(N + 1):
        wd = binom_pmf(d, N, psi)
        if wd < 1e-14:
            continue
        tot += wd * sum(binom_pmf(b, d, pb) for b in rej_b_set(d, alpha))
    return tot


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "power_results_v6.json"))
    a = ap.parse_args(argv)

    # self-checks against v5 RESULTS.md
    assert c_max(376) == 10, c_max(376)                    # "largest c that rejects: 10"
    assert abs(cp_upper(12, 376) - 0.0551) < 5e-4, cp_upper(12, 376)
    assert abs(cp_upper(23, 376) - 0.0904) < 5e-4
    assert abs(mcnemar_p(2, 8) - 0.109375) < 1e-12

    res = {"format": "bran-v6-power/1", "inputs": {"v5_H3a": {"c": V5_C, "n_R": V5_NR, "q_r": V5_C / V5_NR},
                                                   "v5_H1a": {"N": V5_DECISIVE_P, "b": V5_B, "c": V5_C_H1A}},
           "rule": "reject iff one-sided 97.5% Clopper-Pearson upper bound < 0.05 (ceiling unchanged)"}

    res["c_max"] = {str(n): c_max(n) for n in NR_GRID}
    res["H3a_v6_power"] = {str(n): {f"{q:.4f}": power_h3a(n, q) for q in Q_GRID} for n in NR_GRID}

    res["pool_exact"] = {str(n): {"n_total": V5_NR + n, "c_max_total": c_max(V5_NR + n),
                                  "c6_max": c_max(V5_NR + n) - V5_C,
                                  "power": {f"{q:.4f}": power_pool_exact(n, q) for q in Q_GRID}}
                         for n in NR_GRID}
    res["pool_robust"] = {"U5_98.75": cp_upper(V5_C, V5_NR, H3A_ALPHA / 2),
                          "by_n6": {str(n): {"c6_max": pool_robust_cmax(n),
                                             "power": {f"{q:.4f}": power_pool_robust(n, q) for q in Q_GRID}}
                                    for n in NR_GRID}}
    res["predictive_at_nR_376"] = {
        "prior": "q ~ Beta(12.5, 364.5): Jeffreys posterior from v5 (12/376), i.e. v6 harm rate = v5's",
        "H3a_v6": predictive(power_h3a, 376),
        "pool_exact": predictive(power_pool_exact, 376),
        "pool_robust": predictive(power_pool_robust, 376)}

    # joint: v6 passes AND pooled passes at n6 = 376 (pooled exact c6_max >= v6 c_max, so v6 pass => pool pass)
    res["note_nesting"] = ("At every n6 in the grid c6_max(pool exact) >= c_max(v6 alone), so a v6 H3a pass "
                           "implies a pooled pass; the pooled test adds passes for c6 in (c_max, c6_max].")
    for n in NR_GRID:
        assert res["pool_exact"][str(n)]["c6_max"] >= res["c_max"][str(n)]

    # H1a, v6 alone: at v5's observed rates and at weaker effects, N = 526 and 450
    h1 = {}
    psi5, d5 = (V5_B + V5_C_H1A) / V5_DECISIVE_P, (V5_B - V5_C_H1A) / V5_DECISIVE_P
    for N in (526, 450, 400):
        for label, psi, delta in (("v5 observed", psi5, d5), ("half effect", psi5, d5 / 2),
                                  ("planning psi .25 delta .075", 0.25, 0.075)):
            h1[f"N{N} {label}"] = {"psi": psi, "delta": delta,
                                   "power_a0.025": power_mcnemar(N, psi, delta, 0.025),
                                   "power_a0.05": power_mcnemar(N, psi, delta, 0.05)}
    res["H1a_v6_power"] = h1

    # ── VV/VDF (primary family F1 of the v6 draft): H1a(VDF) then H3a(VDF), fixed sequence ──
    vdf = {"inputs": {"source": "v5/selector_study/results.json (post hoc, P)", "b": VDF_B, "c": VDF_C,
                      "N": V5_DECISIVE_P, "H3a_c": VDF_C, "H3a_n_R": V5_NR}}
    vdf["H3a_power"] = {str(n): {f"{q:.4f}": power_h3a(n, q) for q in VDF_Q_GRID} for n in NR_GRID}
    vdf["H3a_predictive_nR_376"] = {
        "prior": "q ~ Beta(4.5, 372.5): Jeffreys posterior from the POST HOC v5 VV/VDF count 4/376 "
                 "(optimistic: VDF was chosen on these data)",
        "value": (lambda: (lambda xs_ws: sum(w * power_h3a(376, q) for q, w in zip(*xs_ws)))(
            beta_grid(VDF_C + 0.5, V5_NR - VDF_C + 0.5)[:2]))()}
    psi_v, d_v = (VDF_B + VDF_C) / V5_DECISIVE_P, (VDF_B - VDF_C) / V5_DECISIVE_P
    h1v = {}
    for N in (526, 450, 400):
        for label, psi, delta in (("v5 post hoc (b87 c4)", psi_v, d_v),
                                  ("half effect, same psi", psi_v, d_v / 2),
                                  ("half b and c (psi/2, delta/2)", psi_v / 2, d_v / 2)):
            h1v[f"N{N} {label}"] = {"psi": psi, "delta": delta,
                                    "power_a0.05": power_mcnemar(N, psi, delta, 0.05),
                                    "power_a0.025": power_mcnemar(N, psi, delta, 0.025)}
    vdf["H1a_power"] = h1v
    # fixed sequence: P(H1a and H3a) >= P(H3a) - (1 - P(H1a))  (Bonferroni lower bound)
    p1 = min(v["power_a0.05"] for k, v in h1v.items() if k.startswith("N526 "))
    vdf["sequence_lower_bound_N526_nR376"] = {
        f"{q:.4f}": max(0.0, power_h3a(376, q) - (1 - p1)) for q in VDF_Q_GRID}
    vdf["sequence_note"] = "H1a power used is the weakest N 526 scenario at alpha 0.05"
    res["VV_VDF"] = vdf

    Path(a.out).write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")

    # print the tables
    print("c_max (v6 alone):", res["c_max"])
    print("\nH3a v6 alone: P(pass)")
    print("n_R | " + " | ".join(f"q={q:.4f}" for q in Q_GRID))
    for n in NR_GRID:
        print(f"{n} | " + " | ".join(f"{power_h3a(n, q):.3f}" for q in Q_GRID))
    print("\nPooled exact (v5 12/376 + v6): c6_max and P(pass)")
    for n in NR_GRID:
        r = res["pool_exact"][str(n)]
        print(f"n6={n} total={r['n_total']} c_tot_max={r['c_max_total']} c6_max={r['c6_max']} | "
              + " | ".join(f"{v:.3f}" for v in r["power"].values()))
    print(f"\nPooled robust (Bonferroni 98.75% CP each, weighted): U5 = {res['pool_robust']['U5_98.75']:.4f}")
    for n in NR_GRID:
        r = res["pool_robust"]["by_n6"][str(n)]
        print(f"n6={n} c6_max={r['c6_max']} | " + " | ".join(f"{v:.3f}" for v in r["power"].values()))
    print("\nPredictive (q from v5 posterior), n_R = 376:", json.dumps(res["predictive_at_nR_376"], indent=1))
    print("\nH1a v6 alone:")
    for k, v in h1.items():
        print(f"{k}: psi={v['psi']:.3f} delta={v['delta']:.3f} power@.025={v['power_a0.025']:.4f} "
              f"power@.05={v['power_a0.05']:.4f}")
    print("\nVV/VDF H3a (v6 alone): P(pass)")
    print("n_R | " + " | ".join(f"q={q:.4f}" for q in VDF_Q_GRID))
    for n in NR_GRID:
        print(f"{n} | " + " | ".join(f"{v:.3f}" for v in vdf["H3a_power"][str(n)].values()))
    print("VV/VDF H3a predictive (n_R 376):", round(vdf["H3a_predictive_nR_376"]["value"], 3))
    print("VV/VDF H1a:")
    for k, v in h1v.items():
        print(f"{k}: psi={v['psi']:.3f} delta={v['delta']:.3f} power@.05={v['power_a0.05']:.4f} "
              f"power@.025={v['power_a0.025']:.4f}")
    print("fixed-sequence lower bound (N 526, n_R 376):",
          {k: round(v, 3) for k, v in vdf["sequence_lower_bound_N526_nR376"].items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
