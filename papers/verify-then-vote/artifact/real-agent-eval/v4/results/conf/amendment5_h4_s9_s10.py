#!/usr/bin/env python3
"""Post-freeze computations pre-declared by PREREGISTRATION.md Amendment 3 (S9) and Amendment 5
(H4, S10, exploratory splits). Not part of the frozen evaluate_v4.py (frozen before Amendment 5).

- H4 and S9 are computed from the frozen per-item table paired_decisions_v4.csv with the frozen
  evaluate_v4.newcombe_paired / mcnemar_p functions (imported, not re-implemented).
- S10 replays every sealed reduction in rust/<id>/<M>.in.json with the frozen binary, timing
  wall-clock per call (1 warm-up + REPS timed runs, median kept), and checks the replay output
  equals the sealed <M>.out.json.
Writes amendment5_v4.json next to this file.
"""
import csv
import hashlib
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
V4 = HERE.parents[1]
sys.path.insert(0, str(V4))
sys.dont_write_bytecode = True
import evaluate_v4 as E  # noqa: E402  frozen analysis module (hash-checked below)

REPS = 5
BIN = V4 / "frozen-bin" / "bran-v4-eval"
freeze = json.load(open(V4 / "FREEZE.json"))
assert E.sha256_file(V4 / "evaluate_v4.py") == freeze["sha256"]["evaluate_v4.py"]
assert E.sha256_file(BIN) == freeze["binary"]["sha256"]

rows = list(csv.DictReader(open(HERE / "paired_decisions_v4.csv")))
for r in rows:
    for k in ("decisive", "M1", "M2", "M3"):
        r[k] = int(r[k])
dec = [r for r in rows if r["decisive"]]


def pair(sub, m1, m2):
    a = sum(1 for r in sub if r[m1] and r[m2]); b = sum(1 for r in sub if r[m1] and not r[m2])
    c = sum(1 for r in sub if r[m2] and not r[m1]); d = sum(1 for r in sub if not r[m1] and not r[m2])
    n = len(sub)
    return {"n": n, "a": a, "b": b, "c": c, "d": d, "acc_" + m1: (a + b) / n, "acc_" + m2: (a + c) / n,
            "diff": (b - c) / n, "p_exact_mcnemar": E.mcnemar_p(b, c), "newcombe_ci95": E.newcombe_paired(a, b, c, d)}


def h4(sub):
    p = pair(sub, "M3", "M2")
    p["margin"] = -0.10
    p["reject_H0_noninferior"] = p["newcombe_ci95"][0] > -0.10
    return p


out = {"H4": {"contrast": "M3 vs M2, H0 acc(M3)-acc(M2) <= -0.10; reject iff Newcombe 95% lower bound > -0.10",
              **h4(dec)}}

# S9: PopQA excluded
s9 = [r for r in dec if r["source"] != "popqa"]
h1 = pair(s9, "M3", "M2"); h1["reject"] = h1["p_exact_mcnemar"] <= 0.05
h2 = pair(s9, "M3", "M1"); h2["noninferior"] = h2["newcombe_ci95"][0] > -0.10
h2["superior"] = h2["noninferior"] and h2["p_exact_mcnemar"] <= 0.05 and h2["b"] > h2["c"]
out["S9_popqa_excluded"] = {"n_decisive": len(s9), "H1": h1, "H2": h2, "H4": h4(s9),
                            "H3": "not computed (no v4 capture/support artifacts sealed)"}

# Exploratory split by S4 score separation
marg = {m["id"]: m for m in csv.DictReader(open(HERE / "separation_margins_v4.csv"))}
split = {}
for lab, f in (("score_separated", lambda r: marg[r["id"]].get("score_separated") in ("1", "True")),
               ("not_score_separated", lambda r: marg[r["id"]].get("score_separated") not in ("1", "True"))):
    sub = [r for r in dec if f(r)]
    split[lab] = pair(sub, "M3", "M2") if sub else {"n": 0}
out["exploratory_M3_minus_M2_by_S4_score_separation"] = split
out["exploratory_by_checked_evidence"] = "not computed (H3 artifacts do not exist for v4)"

# S10
raw = {f.stem: json.load(open(f)) for f in sorted((HERE / "raw").glob("v4-*.json"))}
rust = HERE / "rust"
methods = E.RUST_METHODS
per_item = []
mism = 0
for d in sorted(rust.iterdir()):
    rec = {"id": d.name}
    for m in methods:
        fin = d / f"{m}.in.json"
        sealed = json.load(open(d / f"{m}.out.json"))
        cmd = [str(BIN), "--reduce", str(fin), "--no-color"]
        subprocess.run(cmd, capture_output=True)  # warm-up
        ts = []
        for _ in range(REPS):
            t0 = time.perf_counter(); r = subprocess.run(cmd, capture_output=True, text=True); ts.append(time.perf_counter() - t0)
        if json.loads(r.stdout) != sealed:
            mism += 1
        rec[m + "_s"] = statistics.median(ts)
        rec[m + "_in_bytes"] = fin.stat().st_size
        rec[m + "_out_bytes"] = (d / f"{m}.out.json").stat().st_size
    resp = raw[d.name]["responses"]
    rec["gen_span_s"] = max(x["end_wall"] for x in resp) - min(x["start_wall"] for x in resp)
    rec["gen_sum_s"] = sum(x["elapsed_s"] for x in resp)
    rec["raw_response_bytes"] = sum(len(x["raw_response"].encode()) for x in resp)
    rec["raw_file_bytes"] = (HERE / "raw" / f"{d.name}.json").stat().st_size
    per_item.append(rec)


def q(xs, p):
    xs = sorted(xs); return xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))]


def summ(xs):
    return {"median": statistics.median(xs), "p95": q(xs, 0.95), "max": max(xs)}


s10 = {"n_items": len(per_item), "reps_per_call": REPS, "warmup": 1, "replay_output_mismatches": mism,
       "binary_sha256": E.sha256_file(BIN)}
s10["M3_time_s"] = summ([r["M3_s"] for r in per_item])
s10["all5_time_s"] = summ([sum(r[m + "_s"] for m in methods) for r in per_item])
s10["M3_time_over_gen_span"] = summ([r["M3_s"] / r["gen_span_s"] for r in per_item])
s10["M3_time_over_gen_sum"] = summ([r["M3_s"] / r["gen_sum_s"] for r in per_item])
s10["gen_span_s"] = summ([r["gen_span_s"] for r in per_item])
s10["M3_in_plus_out_over_raw_response_bytes"] = summ([(r["M3_in_bytes"] + r["M3_out_bytes"]) / r["raw_response_bytes"] for r in per_item])
s10["M3_in_plus_out_over_raw_file_bytes"] = summ([(r["M3_in_bytes"] + r["M3_out_bytes"]) / r["raw_file_bytes"] for r in per_item])
s10["totals_bytes"] = {"M3_in": sum(r["M3_in_bytes"] for r in per_item), "M3_out": sum(r["M3_out_bytes"] for r in per_item),
                       "raw_response": sum(r["raw_response_bytes"] for r in per_item),
                       "raw_files": sum(r["raw_file_bytes"] for r in per_item)}
out["S10"] = s10
h = hashlib.sha256()
for f in sorted(rust.rglob("*.json")):
    h.update(f.relative_to(rust).as_posix().encode()); h.update(f.read_bytes())
out["rust_io_tree_sha256"] = h.hexdigest()
json.dump(out, open(HERE / "amendment5_v4.json", "w"), indent=2)
E.write_csv(HERE / "s10_per_item_v4.csv", per_item)
print(json.dumps({"H4": out["H4"], "S9": {k: v for k, v in out["S9_popqa_excluded"].items()}, "S10": s10}, indent=1))
