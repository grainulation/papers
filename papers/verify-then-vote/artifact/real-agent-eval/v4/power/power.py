#!/usr/bin/env python3
"""Eval v4 power analysis (swarm-2 lane L3).

Reads the v3 paired-decision CSVs (no model calls), estimates
  * decisive-conflict yield per question, and
  * the discordant-pair rate psi = (b + c) / n_decisive
for the comparisons relevant to v4, then computes:

  1. exact power of the two-sided exact McNemar test (alpha = 0.05) as a function of the
     number of decisive conflicts N, by exact enumeration over N_disc ~ Binom(N, psi) and
     b | N_disc ~ Binom(N_disc, (psi + delta) / (2 psi)); checked by Monte Carlo;
  2. the smallest N with power >= 0.80 that STAYS >= 0.80 for the next 25 values of N
     (exact-test power is saw-toothed in N), for delta = 0.10 and 0.15;
  3. questions needed = ceil(N / yield) for yields 0.16 (v3 stricter), 0.255 (v3 original),
     0.5, 0.75, 1.0;
  4. a question-clustered design (R runs per question, per-question heterogeneity in the
     discordance direction via a Dirichlet random effect) analysed by (a) naive exact McNemar
     over all conflicts and (b) the Durkalski et al. (2003) clustered McNemar statistic
     X2 = (sum_i (b_i - c_i))^2 / sum_i (b_i - c_i)^2 ~ chi2(1); type-I error and power;
  5. the H2 non-inferiority power (recency-free vs default; margin -0.05, one-sided 0.025).

Usage:  python3 -I power.py [--quick]      (writes power_results.json next to this file)
Deterministic: numpy Generator seeded with SEED.
"""
import csv
import json
import math
import os
import sys
from collections import Counter, defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
V3 = os.path.normpath(os.path.join(HERE, "..", "..", "v3", "results"))
SEED = 20261021
ALPHA = 0.05
N_QUESTIONS_V3 = 55
QUICK = "--quick" in sys.argv

# ---------------------------------------------------------------- exact McNemar


def binom_pmf_vec(n, p):
    k = np.arange(n + 1)
    logc = np.array([math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) for i in k])
    with np.errstate(divide="ignore"):
        lp = logc + k * (math.log(p) if p > 0 else -np.inf) + (n - k) * (math.log1p(-p) if p < 1 else -np.inf)
    lp = np.where(np.isnan(lp), -np.inf, lp)
    return np.exp(lp)


_REJ_CACHE = {}


def rejection_set(n, alpha=ALPHA):
    """Boolean array over b = 0..n: two-sided exact McNemar p <= alpha.
    p = min(1, 2 * min(P(B <= b), P(B >= b))), B ~ Binom(n, 1/2)  (same definition as v3)."""
    if n in _REJ_CACHE:
        return _REJ_CACHE[n]
    if n == 0:
        r = np.array([False])
    else:
        pmf = binom_pmf_vec(n, 0.5)
        cdf = np.cumsum(pmf)
        sf = np.cumsum(pmf[::-1])[::-1]
        p = np.minimum(1.0, 2 * np.minimum(cdf, sf))
        r = p <= alpha + 1e-12
    _REJ_CACHE[n] = r
    return r


def mcnemar_p(b, c):
    n = b + c
    if n == 0:
        return 1.0
    pmf = binom_pmf_vec(n, 0.5)
    return float(min(1.0, 2 * min(pmf[: b + 1].sum(), pmf[b:].sum())))


def exact_power(N, psi, delta, alpha=ALPHA):
    """Power of the exact McNemar test with N independent decisive conflicts.
    psi = P(discordant), delta = P(b) - P(c) (accuracy difference, method minus baseline)."""
    if delta > psi:
        return float("nan")
    pi = (psi + delta) / (2 * psi)
    pd = binom_pmf_vec(N, psi)
    tot = 0.0
    for nd in range(N + 1):
        if pd[nd] < 1e-15:
            continue
        rej = rejection_set(nd, alpha)
        tot += pd[nd] * binom_pmf_vec(nd, pi)[rej].sum()
    return float(tot)


def mc_power(N, psi, delta, reps, rng, alpha=ALPHA):
    pb, pc = (psi + delta) / 2, (psi - delta) / 2
    draws = rng.multinomial(N, [pb, pc, 1 - pb - pc], size=reps)
    hits = 0
    for b, c, _ in draws:
        hits += rejection_set(b + c, alpha)[b]
    return hits / reps


def min_n_stable(psi, delta, target=0.80, nmax=4000, window=25):
    """Smallest N with power >= target for N..N+window (saw-tooth guard)."""
    if delta > psi:
        return None
    # coarse search on a normal-approx starting point
    pi = (psi + delta) / (2 * psi)
    za, zb = 1.959964, 0.841621
    nd = ((za * 0.5 + zb * math.sqrt(pi * (1 - pi))) / (pi - 0.5)) ** 2
    start = max(5, int(0.6 * nd / psi))
    n = start
    pw = {}

    def P(k):
        if k not in pw:
            pw[k] = exact_power(k, psi, delta)
        return pw[k]

    while n > 5 and P(n) >= target:
        n = int(n * 0.9)
    while n <= nmax:
        if P(n) >= target and all(P(n + j) >= target for j in range(1, window + 1)):
            return n
        n += 1
    return None


# ---------------------------------------------------------------- v3 empirics

COMPARISONS = {
    # name: (method column, baseline column)
    "rust_default_vs_majority": ("rust", "majority"),
    "rust_rec0_nodeadband_vs_majority": ("rust_rec0nodb", "majority"),
    "rust_evidence_only_vs_majority": ("rust_evonly", "majority"),
    "last_member_vs_majority": ("last_member", "majority"),
    "rust_default_vs_rust_rec0_nodeadband": ("rust", "rust_rec0nodb"),
}


def v3_empirics():
    out = {}
    for fn in sorted(os.listdir(V3)):
        if not (fn.startswith("paired_decisions_") and fn.endswith(".csv")):
            continue
        rows = list(csv.DictReader(open(os.path.join(V3, fn))))
        dec = [r for r in rows if r["decisive"] == "1"]
        per_q = Counter(r["question"] for r in dec)
        entry = {
            "file": fn,
            "eligible": len(rows),
            "decisive": len(dec),
            "questions_with_decisive": len(per_q),
            "decisive_per_question_distribution": dict(Counter(per_q.values())),
            "yield_decisive_per_question": round(len(dec) / N_QUESTIONS_V3, 4),
            "yield_questions_with_decisive": round(len(per_q) / N_QUESTIONS_V3, 4),
            "comparisons": {},
        }
        for name, (m, base) in COMPARISONS.items():
            if not dec or m not in dec[0] or base not in dec[0]:
                continue
            b = sum(1 for r in dec if r[m] == "1" and r[base] == "0")
            c = sum(1 for r in dec if r[m] == "0" and r[base] == "1")
            entry["comparisons"][name] = {
                "b": b, "c": c, "n": len(dec),
                "psi": round((b + c) / len(dec), 4),
                "delta_hat": round((b - c) / len(dec), 4),
                "p_exact": round(mcnemar_p(b, c), 4),
            }
        # within-question correlation (only questions with >=2 decisive sets)
        multi = [q for q, k in per_q.items() if k >= 2]
        entry["questions_with_2plus_decisive"] = multi
        out[fn.replace("paired_decisions_", "").replace(".csv", "")] = entry
    return out


# ---------------------------------------------------------------- clustered design


def clustered_sim(Q, R, y, psi, delta, kappa, reps, rng):
    """Q questions, R runs each; per-question decisive count K_i ~ Binom(R, y / R), so E[K_i] = y
    (y <= R).
    Each question draws (p_b, p_c, p_0) ~ Dirichlet(kappa * mean) (kappa = inf: no heterogeneity);
    its K_i conflicts are iid multinomial given that draw.
    Returns (power_naive_exact, power_durkalski)."""
    pb, pc = (psi + delta) / 2, (psi - delta) / 2
    mean = np.array([pb, pc, 1 - pb - pc])
    q_run = y / R
    rej_naive = 0
    rej_durk = 0
    crit = 3.841459  # chi2(1) 0.95
    for _ in range(reps):
        K = rng.binomial(R, q_run, size=Q)
        if math.isinf(kappa):
            probs = np.tile(mean, (Q, 1))
        else:
            probs = rng.dirichlet(kappa * mean, size=Q)
        bi = np.zeros(Q, dtype=np.int64)
        ci = np.zeros(Q, dtype=np.int64)
        for i in np.nonzero(K)[0]:
            x = rng.multinomial(K[i], probs[i])
            bi[i], ci[i] = x[0], x[1]
        b, c = int(bi.sum()), int(ci.sum())
        rej_naive += rejection_set(b + c)[b]
        d = bi - ci
        den = float((d * d).sum())
        if den > 0 and (float(d.sum()) ** 2) / den > crit:
            rej_durk += 1
    return rej_naive / reps, rej_durk / reps


def min_q_clustered(R, y, psi, delta, kappa, reps, rng, qmax=6000):
    """Smallest Q (grid step ~5%) with Durkalski power >= 0.80."""
    # start from the independent answer
    n_ind = min_n_stable(psi, delta) or 200
    q = max(10, int(0.7 * n_ind / y))
    last = None
    while q <= qmax:
        _, pd = clustered_sim(q, R, y, psi, delta, kappa, reps, rng)
        if pd >= 0.80:
            return q, pd, last
        last = (q, pd)
        q = int(math.ceil(q * 1.05))
    return None, None, last


# ---------------------------------------------------------------- H2 non-inferiority


def ni_power(N, psi, delta_true, margin=-0.05, reps=4000, rng=None):
    """One-sided 0.025 NI test on paired proportions (Wald CI on d = (b - c)/N with the
    Tango-free simple variance (b + c)/N^2 - d^2/N); reject H0: d <= margin if lower > margin."""
    pb, pc = (psi + delta_true) / 2, (psi - delta_true) / 2
    x = rng.multinomial(N, [pb, pc, 1 - pb - pc], size=reps)
    b, c = x[:, 0], x[:, 1]
    d = (b - c) / N
    var = np.maximum((b + c) / N ** 2 - d ** 2 / N, 1e-12)
    lower = d - 1.959964 * np.sqrt(var)
    return float((lower > margin).mean())


# ---------------------------------------------------------------- main


def main():
    rng = np.random.default_rng(SEED)
    res = {"seed": SEED, "alpha": ALPHA, "quick": QUICK}
    res["v3_empirics"] = v3_empirics()

    deltas = [0.10, 0.15]
    psis = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60, 0.70]
    yields = [0.16, 0.255, 0.50, 0.75, 1.00]
    table = []
    for delta in deltas:
        for psi in psis:
            n = min_n_stable(psi, delta)
            row = {"delta": delta, "psi": psi, "N_decisive_80": n}
            if n is not None:
                row["exact_power_at_N"] = round(exact_power(n, psi, delta), 4)
                row["mc_power_at_N"] = round(mc_power(n, psi, delta, 4000 if QUICK else 20000, rng), 4)
                row["expected_discordant_at_N"] = round(n * psi, 1)
                row["questions_needed"] = {str(y): int(math.ceil(n / y)) for y in yields}
            table.append(row)
    res["independent_design"] = table

    # power achieved by candidate fixed sizes (for the benchmark size decision)
    sizes = [100, 150, 200, 250, 300, 400, 500, 600, 800]
    res["power_at_fixed_N"] = [
        {"N_decisive": n, "psi": psi, "delta": d, "power": round(exact_power(n, psi, d), 3)}
        for n in sizes for psi in (0.25, 0.35, 0.50) for d in deltas
    ]

    # clustered designs (central psi; heterogeneity kappa)
    reps = 400 if QUICK else 1500
    clus = []
    for R in (1, 3):
        for y in ((0.5, 1.0) if R == 1 else (0.75, 1.5, 3.0)):
            if y > R:
                continue
            # with R = 1 a question has at most one decisive conflict, so kappa is irrelevant
            for kappa in ((math.inf,) if R == 1 else (math.inf, 10.0, 2.0)):
                for delta in deltas:
                    psi = 0.35
                    q, pw, last = min_q_clustered(R, y, psi, delta, kappa, reps, rng)
                    t1n, t1d = clustered_sim(q or 500, R, y, psi, 0.0, kappa, reps, rng)
                    clus.append({
                        "runs_per_question": R, "yield_per_question": y, "kappa": None if math.isinf(kappa) else kappa,
                        "psi": psi, "delta": delta, "questions_80_durkalski": q,
                        "power_at_q": pw, "typeI_naive_exact_at_q": round(float(t1n), 3),
                        "typeI_durkalski_at_q": round(t1d, 3), "reps": reps,
                    })
    res["clustered_design"] = clus

    # H2 non-inferiority: default vs recency-free; v3 discordance between them
    res["h2_noninferiority"] = [
        {"N_decisive": n, "psi": psi, "delta_true": 0.0, "margin": m,
         "power": round(ni_power(n, psi, 0.0, margin=m, rng=rng, reps=2000 if QUICK else 10000), 3)}
        for m in (-0.05, -0.10) for n in (150, 300, 500, 800) for psi in (0.10, 0.20, 0.35)
    ]

    # power of the actual v4 design: 600 primary (+400 extension) confirmatory items, one run each
    res["v4_design_power"] = [
        {"items": items, "yield": y, "N_decisive": int(round(items * y)), "psi": psi, "delta": d,
         "power": round(exact_power(int(round(items * y)), psi, d), 3)}
        for items in (600, 1000) for y in (0.16, 0.255, 0.35, 0.5, 0.75) for psi in (0.25, 0.35, 0.5)
        for d in deltas
    ]

    out = os.path.join(HERE, "power_results.json")
    with open(out, "w") as f:
        json.dump(res, f, indent=1, sort_keys=True)
    print("wrote", out)
    for r in table:
        print(r["delta"], r["psi"], r.get("N_decisive_80"), r.get("exact_power_at_N"), r.get("mc_power_at_N"), r.get("questions_needed"))
    for c in clus:
        print(c)


if __name__ == "__main__":
    main()
