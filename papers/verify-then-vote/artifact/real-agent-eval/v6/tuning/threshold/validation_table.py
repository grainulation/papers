"""Supports precision/recall by cutoff T for checker 0.2.0, validation data only. Run: python3 validation_table.py"""
import json, collections
V = "tools/evidence/support/validation/results/"
def L(f): return [json.loads(l) for l in open(V + f)]
C = "f2a14bd8988371bd231ca6ff137be13e"
SL = {"FEVER fresh2 (300)": L(f"fresh2_fever-{C}.jsonl"), "SciFact fresh2 (150, NEI gold only)": L(f"fresh2_scifact-{C}.jsonl")}
TS = [0, 5000, 6000, 7000, 8000, 9000, 9500, 9700, 9900]
out = {}
for n, R in SL.items():
    gold_s = sum(r["gold"] == "supports" for r in R)
    print(n, "gold supports:", gold_s)
    print(" score_q dist (predicted supports):", sorted(collections.Counter(r["score_q"] for r in R if r["label"] == "supports").items()))
    for T in TS:
        P = [r for r in R if r["label"] == "supports" and r["score_q"] >= T]
        tp = sum(r["gold"] == "supports" for r in P)
        prec = tp / len(P) if P else None
        rec = tp / gold_s if gold_s else None
        out[(n, T)] = (len(P), tp, prec, rec)
        print(f"  T={'any' if T==0 else T}: n_sup={len(P)} tp={tp} prec={prec} recall={rec}")
