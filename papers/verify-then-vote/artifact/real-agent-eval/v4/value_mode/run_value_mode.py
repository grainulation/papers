#!/usr/bin/env python3
"""Candidate grouping by value on the v3 real-agent inputs.

For every stored v3 reducer input real-agent-eval/v3/results/rust/<ds>/<q>/<variant>.in.json
(variants `forced` = Table A's Python-structured slots, `native` = Table B's Rust-native
slots), this script

  1. re-runs the stored input unchanged with the given binary and checks the output is
     byte-for-byte the stored <variant>.out.json (member mode, default candidate_mode);
  2. overlays `policy.candidate_mode = {"mode": "value", "aggregate": A}` for A in
     {max, pooled}, runs `overturn --reduce`, and stores in/out under
     real-agent-eval/v4/value_mode/rust/<ds>/<q>/<variant>_value_<A>.{in,out}.json;
  3. scores Table A (and Table B) exactly as real-agent-eval/v3/evaluate_v3.py does,
     by importing it (not modifying it): same eligible/decisive rows, same graders
     (ev2.GRADERS: v1 = original, v2 = stricter), same outcome rule
     (evaluate_v3.rust_outcome + outcome_correct), McNemar vs majority
     (ev2.mcnemar_exact) and question-clustered bootstrap (ev2.cluster_bootstrap).

Usage: python3 run_value_mode.py --bin <path/to/overturn> [--bootstrap 10000 --seed 42]
Writes results.json, winner_changes_<ds>.csv and paired_<ds>_<table>_<grader>.csv here.
"""
import argparse
import copy
import csv
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
V3 = HERE.parent.parent / "v3"
sys.path.insert(0, str(V3))
import evaluate_v3 as e3  # noqa: E402

ev2, v1 = e3.ev2, e3.v1
AGGS = ["max", "pooled"]
VARIANTS = ["forced", "native"]
METHODS = ["rust_member", "rust_value_max", "rust_value_pooled", "majority", "first_member", "last_member"]


def reduce(binary, fin):
    r = subprocess.run([binary, "--reduce", str(fin), "--no-color"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"overturn --reduce failed on {fin}: {r.stderr}")
    return r.stdout


def run_all(binary, ds, qid):
    src = V3 / "results" / "rust" / ds / qid
    outs, regress = {}, {}
    for var in VARIANTS:
        fin = src / f"{var}.in.json"
        stored = json.load(open(src / f"{var}.out.json"))
        fresh = json.loads(reduce(binary, fin))
        regress[var] = fresh == stored
        outs[(var, "member")] = stored
        inp = json.load(open(fin))
        for agg in AGGS:
            vi = copy.deepcopy(inp)
            vi["policy"]["candidate_mode"] = {"mode": "value", "aggregate": agg}
            d = HERE / "rust" / ds / qid
            d.mkdir(parents=True, exist_ok=True)
            vin = d / f"{var}_value_{agg}.in.json"
            json.dump(vi, open(vin, "w"), indent=1, sort_keys=True)
            out = json.loads(reduce(binary, vin))
            json.dump(out, open(d / f"{var}_value_{agg}.out.json", "w"), indent=1, sort_keys=True)
            outs[(var, f"value_{agg}")] = out
    return outs, regress


def val(c):
    return e3.norm_obj(c["object"])


def winner_changes(ds, runs):
    """Per Rust contradiction slot: did the winning id / winning value change vs member?"""
    rows = []
    for r in runs:
        by_id = r["by_id"]
        for var in VARIANTS:
            base = {frozenset(s["members"]): s for s in r["outs"][(var, "member")]["selections"]
                    if s["type"] == "CONTRADICTION"}
            for agg in AGGS:
                other = {frozenset(s["members"]): s for s in r["outs"][(var, f"value_{agg}")]["selections"]
                         if s["type"] == "CONTRADICTION"}
                assert set(base) == set(other), "value mode must not change slot structure"
                for k, s in base.items():
                    o = other[k]
                    rows.append({"dataset": ds, "question": r["q"]["id"], "variant": var, "aggregate": agg,
                                 "slot": s["slot"], "n_members": len(s["members"]),
                                 "n_values": len({val(by_id[i]) for i in s["members"]}),
                                 "member_winner_object": val(by_id[s["winner"]]),
                                 "value_winner_object": val(by_id[o["winner"]]),
                                 "member_in_deadband": int(s["in_deadband"]),
                                 "value_in_deadband": int(o["in_deadband"]),
                                 "winner_id_changed": int(s["winner"] != o["winner"]),
                                 "winner_value_changed": int(val(by_id[s["winner"]]) != val(by_id[o["winner"]]))})
    return rows


def table_a(runs, grader):
    rows = []
    for r in runs:
        gt, by_id = r["gt"], r["by_id"]
        for cs in r["cs"]:
            if cs["type"] != "contradiction":
                continue
            mem = cs["members"]
            flags = [e3.correct(m, gt, grader) for m in mem]
            if not any(flags):
                continue
            ids = [m["_id"] for m in mem]
            row = {"question": r["q"]["id"], "subject": cs["key"][0], "predicate": cs["key"][1],
                   "n_members": len(mem), "n_values": len({val(m) for m in mem}),
                   "decisive": int(not all(flags))}
            for mode in ["member", "value_max", "value_pooled"]:
                kind, adm, _ = e3.rust_outcome(ids, r["outs"][("forced", mode)])
                row[f"rust_{mode}"] = e3.outcome_correct(adm, by_id, gt, grader)
                row[f"outcome_{mode}"] = kind
            row["majority"] = int(flags[ev2.majority_idx(mem)])
            row["first_member"] = int(flags[0])
            row["last_member"] = int(flags[-1])
            rows.append(row)
    return rows


def table_b(runs, grader):
    rows = []
    for r in runs:
        gt, by_id = r["gt"], r["by_id"]
        idx = {mode: {frozenset(s["members"]): s for s in e3.rust_index(r["outs"][("native", mode)])[0]}
               for mode in ["member", "value_max", "value_pooled"]}
        for k, s in idx["member"].items():
            mem = [by_id[i] for i in s["members"]]
            flags = [e3.correct(m, gt, grader) for m in mem]
            if not any(flags):
                continue
            fl = dict(zip(s["members"], flags))
            row = {"question": r["q"]["id"], "slot": s["slot"], "n_members": len(mem),
                   "n_values": len({val(m) for m in mem}), "decisive": int(not all(flags))}
            for mode in idx:
                row[f"rust_{mode}"] = int(fl[idx[mode][k]["winner"]])
            row["majority"] = int(flags[ev2.majority_idx(mem)])
            row["first_member"] = int(flags[0])
            row["last_member"] = int(flags[-1])
            rows.append(row)
    return rows


def stats(rows, args):
    dec = [r for r in rows if r["decisive"]]
    st = {"eligible": len(rows), "decisive": len(dec), "accuracy": {}, "vs_majority": {}, "vs_member": {}}
    for m in METHODS:
        st["accuracy"][m] = {"eligible_correct": sum(r[m] for r in rows), "decisive_correct": sum(r[m] for r in dec)}
        if m != "majority":
            b = sum(1 for r in rows if r[m] and not r["majority"])
            c = sum(1 for r in rows if r["majority"] and not r[m])
            st["vs_majority"][m] = {"b": b, "c": c, "p_exact": ev2.mcnemar_exact(b, c)}
        if m.startswith("rust_value"):
            b = sum(1 for r in rows if r[m] and not r["rust_member"])
            c = sum(1 for r in rows if r["rust_member"] and not r[m])
            st["vs_member"][m] = {"b": b, "c": c, "p_exact": ev2.mcnemar_exact(b, c)}
    if rows:
        st["bootstrap_minus_majority"] = {}
        for m in ["rust_member", "rust_value_max", "rust_value_pooled"]:
            pt, lo, hi, nq = ev2.cluster_bootstrap(rows, m, "majority", args.bootstrap, args.seed)
            st["bootstrap_minus_majority"][m] = {"diff": pt, "ci95": [lo, hi], "n_questions": nq}
    return st


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", required=True)
    ap.add_argument("--bootstrap", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--datasets", nargs="*", default=["v3", "v1orig"])
    args = ap.parse_args()
    res = {"binary_sha256": hashlib.sha256(open(args.bin, "rb").read()).hexdigest(), "datasets": {}}
    for ds in args.datasets:
        runs, reg = [], Counter()
        for q, resps, tag in e3.load_dataset(ds):
            assert tag == ""
            contribs = e3.build_contribs(q, resps)
            outs, regress = run_all(args.bin, ds, q["id"])
            for var, ok in regress.items():
                reg[(var, ok)] += 1
            runs.append({"q": q, "gt": [tuple(x) for x in q["ground_truth"]], "contribs": contribs,
                         "by_id": {c["_id"]: c for c in contribs}, "outs": outs,
                         "cs": v1.detect_conflicts(contribs)})
        wc = winner_changes(ds, runs)
        write_csv(HERE / f"winner_changes_{ds}.csv", wc)
        dres = {"questions": len(runs),
                "member_mode_regression": {f"{v}|{'identical' if ok else 'DIFFERENT'}": n for (v, ok), n in sorted(reg.items())},
                "policy_hashes": {f"{v}|{m}": sorted({r["outs"][(v, m)]["policy_hash"] for r in runs})[:1] + [
                    f"{len({r['outs'][(v, m)]['policy_hash'] for r in runs})} distinct"]
                    for v in VARIANTS for m in ["member", "value_max", "value_pooled"]},
                "winner_changes": {}, "tables": {}}
        for var in VARIANTS:
            for agg in AGGS:
                sub = [x for x in wc if x["variant"] == var and x["aggregate"] == agg]
                multi = [x for x in sub if x["n_values"] < x["n_members"]]
                dres["winner_changes"][f"{var}|{agg}"] = {
                    "contradiction_slots": len(sub),
                    "slots_with_repeated_value": len(multi),
                    "winner_id_changed": sum(x["winner_id_changed"] for x in sub),
                    "winner_value_changed": sum(x["winner_value_changed"] for x in sub),
                    "deadband_member": sum(x["member_in_deadband"] for x in sub),
                    "deadband_value": sum(x["value_in_deadband"] for x in sub)}
        for gname, grader in ev2.GRADERS.items():
            for tname, fn in [("A_python_slots", table_a), ("B_rust_native_slots", table_b)]:
                rows = fn(runs, grader)
                write_csv(HERE / f"paired_{ds}_{tname}_{gname}.csv", rows)
                dres["tables"][f"{tname}|{gname}"] = stats(rows, args)
        res["datasets"][ds] = dres
    json.dump(res, open(HERE / "results.json", "w"), indent=2)
    for ds, d in res["datasets"].items():
        print(f"\n## {ds}  regression={d['member_mode_regression']}")
        print("winner changes:", json.dumps(d["winner_changes"]))
        for k, t in d["tables"].items():
            acc = " | ".join(f"{m} {t['accuracy'][m]['eligible_correct']}·{t['accuracy'][m]['decisive_correct']}" for m in METHODS)
            print(f"{k} ({t['eligible']}/{t['decisive']}): {acc}")
            print("   vs maj:", {m: (v['b'], v['c'], round(v['p_exact'], 4)) for m, v in t["vs_majority"].items() if m.startswith('rust')},
                  " vs member:", {m: (v['b'], v['c'], round(v['p_exact'], 4)) for m, v in t["vs_member"].items()})


if __name__ == "__main__":
    main()
