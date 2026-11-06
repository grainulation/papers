#!/usr/bin/env python3
"""
Eval v6 secondary analyses across the two pools (PREREGISTRATION.md sections 2.3 and 2.4). BE-G only for the pooled H3a.

Reads `evaluation_v5.json` (prereg block) and `paired_decisions_v5.csv` from the v5 and the v6 confirmatory eval directories
(and, for the VDF rows of the cross-pool table, `evaluation_v6_vdf.json` and v5's post-hoc selector_study/results.json).
No model call, no hosted call.

H3a-pool (secondary, declared after v5's H3a miss; the v5 half is fixed at c = 12, n_R = 376):
  * exact test (decides H3a-pool): one-sided 97.5% Clopper-Pearson upper bound on (12 + c6) / (376 + n_R6), < 0.05 rejects;
  * dependence-robust sensitivity: U = (376*U5 + nR6*U6) / (376 + nR6), each U a one-sided 98.75% CP bound (U5 = 0.0587);
    holds robustly iff U < 0.05 (Bonferroni: q_pool <= U with probability >= 0.975 under any dependence);
  * items that are c-events in both pools; item-cluster bootstrap 95% interval of q_pool (10,000 resamples, seed 42).
Cross-pool table (2.4, descriptive): v6 - v5 differences in (b-c)/N, q_r and p_w for BE-G, BE, VV (and the VDF rows, whose
v5 side is the post-hoc selector-study value) on P and T, with Newcombe hybrid intervals for independent estimates.

Usage
  pooled_h3a_v6.py --v5 v5/results/conf/eval --v6 v6/results/conf/eval --out v6/results/conf/pooled_h3a_v6.json
"""
import argparse
import csv
import importlib.util
import json
import math
import random
import sys
from pathlib import Path

sys.dont_write_bytecode = True
V6 = Path(__file__).resolve().parent
V5 = V6.parent / "v5"


def _load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


PW = _load("power_v6", V6 / "power" / "power_v6.py")     # cp_upper, as the prereg says
E = _load("evaluate_v5", V5 / "evaluate_v5.py")          # wilson, newcombe_paired (read-only helpers)

BOUND, ALPHA = PW.H3A_BOUND, PW.H3A_ALPHA                # 0.05, 0.025
V5_C, V5_NR = PW.V5_C, PW.V5_NR                          # 12, 376 (prereg 2.3)


# ── pooled H3a ──────────────────────────────────────────────────

def pooled_exact(c5, n5, c6, n6):
    """Exact pooled one-sided 97.5% CP test: reject iff the upper bound on (c5 + c6) / (n5 + n6) is below 0.05."""
    n, c = n5 + n6, c5 + c6
    ub = PW.cp_upper(c, n, ALPHA)
    cmax = PW.c_max(n)
    return {"c": c, "n": n, "q_pool": c / n if n else None, "cp_upper_97_5": ub, "reject": bool(ub is not None and ub < BOUND),
            "c6_allowed": cmax - c5, "c_max_pooled": cmax}


def pooled_robust(c5, n5, c6, n6):
    """U = (n5*U5 + n6*U6) / (n5 + n6) with one-sided 98.75% CP bounds (alpha/2 each); holds iff U < 0.05."""
    u5, u6 = PW.cp_upper(c5, n5, ALPHA / 2), PW.cp_upper(c6, n6, ALPHA / 2)
    u = (n5 * u5 + n6 * u6) / (n5 + n6)
    return {"U5": u5, "U6": u6, "U": u, "holds_robustly": bool(u < BOUND), "c6_allowed": PW.pool_robust_cmax(n6)}


def cluster_bootstrap(items, n_boot=10000, seed=42):
    """items: list of (c5, r5, c6, r6) per item (an item is the cluster). 95% percentile interval of
    (sum c5 + sum c6) / (sum r5 + sum r6) over item resamples."""
    n = len(items)
    rng = random.Random(seed)
    qs = []
    for _ in range(n_boot):
        c = r = 0
        for _ in range(n):
            x = items[rng.randrange(n)]
            c += x[0] + x[2]
            r += x[1] + x[3]
        if r:
            qs.append(c / r)
    qs.sort()
    return {"resamples": n_boot, "seed": seed, "unit": "item", "n_items": n,
            "ci95": [qs[int(0.025 * len(qs))], qs[min(len(qs) - 1, int(0.975 * len(qs)))]] if qs else None}


# ── cross-pool differences ──────────────────────────────────────

def diff_ci(t1, ci1, t2, ci2):
    """Newcombe's hybrid interval for the difference of two independent estimates t1 - t2 from their own intervals."""
    d = t1 - t2
    lo = d - math.sqrt((t1 - ci1[0]) ** 2 + (ci2[1] - t2) ** 2)
    hi = d + math.sqrt((ci1[1] - t1) ** 2 + (t2 - ci2[0]) ** 2)
    return [lo, hi]


def metrics(n, b, c, nw, nr):
    """(b-c)/N with its paired Newcombe CI, q_r = c/#right and p_w = b/#wrong with Wilson CIs."""
    a, d = nr - c, nw - b
    return {"n": n, "b": b, "c": c, "net": (b - c) / n if n else None, "net_ci95": E.newcombe_paired(a, b, c, d),
            "q_r": c / nr if nr else None, "q_r_ci95": E.wilson(c, nr), "p_w": b / nw if nw else None, "p_w_ci95": E.wilson(b, nw)}


def compare(m5, m6):
    out = {"v5": m5, "v6": m6}
    for k, ck in (("net", "net_ci95"), ("q_r", "q_r_ci95"), ("p_w", "p_w_ci95")):
        if None in (m5[k], m6[k], m5[ck], m6[ck]):
            out[f"{k}_v6_minus_v5"] = None
        else:
            out[f"{k}_v6_minus_v5"] = {"diff": m6[k] - m5[k], "newcombe_ci95": diff_ci(m6[k], m6[ck], m5[k], m5[ck])}
    return out


def from_overturn(o):
    return metrics(o["n"], o["b"], o["c"], o["base_wrong"], o["base_right"])


def read_rows(path):
    with open(path, newline="") as f:
        return {r["id"]: r for r in csv.DictReader(f)}


def decisive_counts(rows, s):
    d = [r for r in rows.values() if r["set"] == s and r["decisive"] == "1"]
    nw = sum(1 for r in d if r["MAJ"] == "0")
    return len(d), nw, len(d) - nw


def analyse(v5_dir, v6_dir, selector_path, n_boot=10000, seed=42):
    v5_dir, v6_dir = Path(v5_dir), Path(v6_dir)
    ev5, ev6 = E.jload(v5_dir / "evaluation_v5.json"), E.jload(v6_dir / "evaluation_v5.json")
    h5, h6 = ev5["prereg"]["H3"]["H3a"], ev6["prereg"]["H3"]["H3a"]
    if (h5["c"], h5["n_R"]) != (V5_C, V5_NR):
        raise SystemExit(f"ABORT: v5 H3a is {h5['c']}/{h5['n_R']}, the preregistered fixed half is {V5_C}/{V5_NR}")
    if h5["method"] != "BE-G" or h6["method"] != "BE-G":
        raise SystemExit("ABORT: H3a-pool is defined for BE-G only")
    rows5, rows6 = read_rows(v5_dir / "paired_decisions_v5.csv"), read_rows(v6_dir / "paired_decisions_v5.csv")

    def cevents(rows):
        right = {i for i, r in rows.items() if r["set"] == "P" and r["decisive"] == "1" and r["MAJ"] == "1"}
        return right, {i for i in right if rows[i]["BE-G"] == "0"}

    r5, c5 = cevents(rows5)
    r6, c6 = cevents(rows6)
    if (len(c5), len(r5)) != (h5["c"], h5["n_R"]) or (len(c6), len(r6)) != (h6["c"], h6["n_R"]):
        raise SystemExit("ABORT: per-item rows do not reproduce the H3a blocks")
    out = {"declared": "after v5's H3a result was known; BE-G only; secondary; reported after H3a-rep; never computed for VDF",
           "v5": {"c": h5["c"], "n_R": h5["n_R"], "cp_upper_97_5": h5["cp_upper_97_5"], "reject": h5["reject"]},
           "v6": {"c": h6["c"], "n_R": h6["n_R"], "cp_upper_97_5": h6["cp_upper_97_5"], "reject": h6["reject"]}}
    out["pooled_exact"] = pooled_exact(h5["c"], h5["n_R"], h6["c"], h6["n_R"])
    out["pooled_robust"] = pooled_robust(h5["c"], h5["n_R"], h6["c"], h6["n_R"])
    both = sorted(c5 & c6)
    out["c_events_in_both_pools"] = {"count": len(both), "items": both, "v5_only": len(c5 - c6), "v6_only": len(c6 - c5),
                                     "right_majority_in_both": len(r5 & r6)}
    ids = sorted(i for i in set(rows5) | set(rows6) if (rows5.get(i) or rows6.get(i))["set"] == "P")
    cl = [(int(i in c5), int(i in r5), int(i in c6), int(i in r6)) for i in ids]
    out["bootstrap"] = cluster_bootstrap(cl, n_boot, seed)
    out["bootstrap"]["q_pool_point"] = out["pooled_exact"]["q_pool"]
    # §2.4 cross-pool table
    table = {}
    for s in ("P", "T"):
        table[s] = {}
        for m in ("BE-G", "BE", "VV"):
            table[s][m] = compare(from_overturn(ev5["prereg"]["overturn_vs_MAJ"][s][m]),
                                  from_overturn(ev6["prereg"]["overturn_vs_MAJ"][s][m]))
    vdf6 = v6_dir / "evaluation_v6_vdf.json"
    if vdf6.exists() and Path(selector_path).exists():
        sel = E.jload(selector_path)["variants"]
        v6 = E.jload(vdf6)
        for s in ("P", "T"):
            n5, nw5, nr5 = decisive_counts(rows5, s)
            for m in ("VV/VDF", "BE-G/VDF"):
                o5 = sel[m][s]
                m5 = metrics(o5["n"], o5["b_vs_MAJ"], o5["c_vs_MAJ"], nw5, nr5)
                table[s][m] = compare(m5, from_overturn(v6["overturn_vs_MAJ"][s][m]))
                table[s][m]["v5_side"] = "post hoc (v5/selector_study), not confirmatory"
    out["cross_pool_table"] = {"note": ("descriptive; items are reused so the pools are positively correlated and no test of 'same effect "
                                        "in both pools' is made; intervals are Newcombe hybrid for independent estimates"),
                               "table": table}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="eval v6 pooled H3a and cross-pool table")
    ap.add_argument("--v5", required=True, help="v5 confirmatory eval dir (evaluation_v5.json, paired_decisions_v5.csv)")
    ap.add_argument("--v6", required=True, help="v6 confirmatory eval dir (same files, plus evaluation_v6_vdf.json)")
    ap.add_argument("--selector", default=str(V5 / "selector_study" / "results.json"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--bootstrap", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args(argv)
    res = analyse(a.v5, a.v6, a.selector, a.bootstrap, a.seed)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    pe, pr = res["pooled_exact"], res["pooled_robust"]
    print(json.dumps({"pooled_exact": {k: pe[k] for k in ("c", "n", "cp_upper_97_5", "reject", "c6_allowed")},
                      "pooled_robust": {k: pr[k] for k in ("U", "holds_robustly", "c6_allowed")},
                      "c_events_in_both_pools": res["c_events_in_both_pools"]["count"],
                      "bootstrap_ci95": res["bootstrap"]["ci95"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
