#!/usr/bin/env python3
"""
Lane L10: re-run the v3 analysis (real-agent-eval/v3/evaluate_v3.py) with deterministic
object canonicalization (canon.py) applied before
  * Python conflict-set construction (evaluate_v1.detect_conflicts),
  * majority vote (evaluate_v2.majority_idx), and
  * the Rust reducer input (`bran --reduce`, canonical_form.object),
identically for every method.

Nothing in v3/ is modified. evaluate_v3.py is imported and its module globals are
re-bound for this process only:
  OUT             -> results/<mode>/           (all Rust in/out JSON, CSVs land here)
  build_contribs  -> original + object := canon(object)   (contribution ids are still
                     hashed from the RAW object, so ids match v3 one-to-one)
  DEFAULT_POLICY  -> incompatible_values entries canonicalized the same way
  correct         -> graders see the RAW object (canonicalization changes what the
                     reducers compare, never what the grader judges)

Modes: `raw` (no canonicalization; must reproduce v3/results/evaluation_v3.json) and
`canon`. Usage:
  python3 run_canon.py --bin <bran> [--bootstrap 10000 --seed 42]
"""

import argparse
import copy
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.dont_write_bytecode = True                  # never write __pycache__ into read-only v3/
HERE = Path(__file__).resolve().parent
EVAL = HERE.parent.parent                      # real-agent-eval/
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(EVAL / "v3"))
sys.path.insert(0, str(EVAL))
import canon as C                               # noqa: E402
import evaluate_v1 as v1                        # noqa: E402
import evaluate_v2 as ev2                       # noqa: E402
import evaluate_v3 as e3                        # noqa: E402

RESULTS = HERE / "results"
ORIG = {"build_contribs": e3.build_contribs, "DEFAULT_POLICY": copy.deepcopy(e3.DEFAULT_POLICY),
        "correct": e3.correct, "nearest_gold": ev2.nearest_gold,
        "adjudication_category": ev2.adjudication_category}


def raw_view(c):
    if "_raw_object" in c:
        c = dict(c)
        c["object"] = c["_raw_object"]
    return c


def set_mode(mode):
    out = RESULTS / mode
    out.mkdir(parents=True, exist_ok=True)
    e3.OUT = out
    if mode == "raw":
        e3.build_contribs = ORIG["build_contribs"]
        e3.DEFAULT_POLICY = copy.deepcopy(ORIG["DEFAULT_POLICY"])
        e3.correct = ORIG["correct"]
        ev2.nearest_gold = ORIG["nearest_gold"]
        ev2.adjudication_category = ORIG["adjudication_category"]
        return out

    def build_canon(q, resps):
        cs = ORIG["build_contribs"](q, resps)
        for c in cs:
            c["_raw_object"] = c["object"]
            c["object"] = C.canon(c["object"])
        return cs
    pol = copy.deepcopy(ORIG["DEFAULT_POLICY"])
    iv = pol["values"]["incompatible_values"]
    for pr in iv:
        for g in iv[pr]:
            iv[pr][g] = sorted({C.canon(o) for o in iv[pr][g]})
    e3.build_contribs = build_canon
    e3.DEFAULT_POLICY = pol
    e3.correct = lambda c, gt, grader: ev2.correct_any(raw_view(c), gt, grader)
    ev2.nearest_gold = lambda c, gt: ORIG["nearest_gold"](raw_view(c), gt)
    ev2.adjudication_category = lambda c, gt: ORIG["adjudication_category"](raw_view(c), gt)
    return out


# ── Canonicalization effect on conflict structure & majority ────

def majority_profile(members):
    cnt = Counter(m["object"].lower().strip() for m in members)
    top = cnt.most_common()
    first_obj = members[0]["object"].lower().strip()
    win_obj = members[ev2.majority_idx(members)]["object"].lower().strip()
    return {"top": top[0][1], "second": top[1][1] if len(top) > 1 else 0,
            "distinct": len(cnt), "winner_is_first_member": int(win_obj == first_obj)}


def structure_stats(dsname, data):
    """Compare RAW vs CANON Python conflict sets on identical contributions."""
    rows, merges = [], []
    agg = Counter()
    for q, resps, tag in data:
        raw = ORIG["build_contribs"](q, resps)
        can = copy.deepcopy(raw)
        for c in can:
            c["_raw_object"] = c["object"]
            c["object"] = C.canon(c["object"])
        gt = [tuple(x) for x in q["ground_truth"]]
        rs = {cs["key"]: cs for cs in v1.detect_conflicts(raw)}
        ks = {cs["key"]: cs for cs in v1.detect_conflicts(can)}
        assert rs.keys() == ks.keys()             # subjects/predicates untouched
        for k in sorted(rs):
            r, c = rs[k], ks[k]
            if r["type"] != "contradiction":
                assert c["type"] != "contradiction"
                continue
            mr, mc = majority_profile(r["members"]), majority_profile(c["members"])
            dissolved = int(c["type"] == "redundancy")
            row = {"dataset": dsname, "question": q["id"], "subject": k[0], "predicate": k[1],
                   "n_members": len(r["members"]),
                   "distinct_raw": mr["distinct"], "distinct_canon": mc["distinct"],
                   "dissolved": dissolved,
                   "majority_top_raw": mr["top"], "majority_top_canon": mc["top"],
                   "real_majority_raw": int(mr["top"] > 1), "real_majority_canon": int(mc["top"] > 1),
                   "strict_plurality_raw": int(mr["top"] > 1 and mr["top"] > mr["second"]),
                   "strict_plurality_canon": int(mc["top"] > 1 and mc["top"] > mc["second"]),
                   "majority_is_first_raw": mr["winner_is_first_member"],
                   "majority_is_first_canon": mc["winner_is_first_member"]}
            for gname, grader in ev2.GRADERS.items():
                fl = [ev2.correct_any(raw_view(m), gt, grader) for m in c["members"]]
                row[f"eligible_raw_{gname}"] = int(any(fl))
                row[f"decisive_raw_{gname}"] = int(any(fl) and not all(fl))
            rows.append(row)
            # merge audit: canonical classes covering >1 distinct raw strings
            cls = defaultdict(list)
            for m in c["members"]:
                cls[m["object"]].append(m)
            for cobj, mem in sorted(cls.items()):
                raws = sorted({m["_raw_object"].lower().strip() for m in mem})
                if len(raws) < 2:
                    continue
                mrow = {"dataset": dsname, "question": q["id"], "subject": k[0], "predicate": k[1],
                        "canonical_object": cobj, "n_members": len(mem),
                        "raw_variants": " || ".join(raws)}
                for gname, grader in ev2.GRADERS.items():
                    fl = [int(ev2.correct_any(raw_view(m), gt, grader)) for m in mem]
                    mrow[f"grader_{gname}_member_correct"] = "".join(map(str, fl))
                    mrow[f"grader_{gname}_mixed"] = int(0 < sum(fl) < len(fl))
                merges.append(mrow)
    n = len(rows)
    agg = {"raw_contradiction_sets": n,
           "dissolved_formatting_only": sum(r["dissolved"] for r in rows),
           "canon_contradiction_sets": n - sum(r["dissolved"] for r in rows),
           "sets_with_fewer_distinct_objects": sum(r["distinct_canon"] < r["distinct_raw"] for r in rows),
           "real_majority_raw": sum(r["real_majority_raw"] for r in rows),
           "real_majority_canon_all_raw_sets": sum(r["real_majority_canon"] for r in rows),
           "real_majority_canon_surviving_sets": sum(r["real_majority_canon"] for r in rows if not r["dissolved"]),
           "strict_plurality_raw": sum(r["strict_plurality_raw"] for r in rows),
           "strict_plurality_canon_surviving_sets": sum(r["strict_plurality_canon"] for r in rows if not r["dissolved"]),
           "majority_winner_not_first_raw": sum(1 - r["majority_is_first_raw"] for r in rows),
           "majority_winner_not_first_canon_surviving": sum(1 - r["majority_is_first_canon"] for r in rows if not r["dissolved"]),
           "merge_classes": len(merges),
           "merge_classes_mixed_correctness": {g: sum(m[f"grader_{g}_mixed"] for m in merges) for g in ev2.GRADERS}}
    for g in ev2.GRADERS:
        el = [r for r in rows if r[f"eligible_raw_{g}"]]
        de = [r for r in rows if r[f"decisive_raw_{g}"]]
        agg[f"grader_{g}"] = {
            "raw_eligible": len(el), "raw_decisive": len(de),
            "eligible_dissolved": sum(r["dissolved"] for r in el),
            "decisive_dissolved": sum(r["dissolved"] for r in de),
            "eligible_surviving_real_majority_raw": sum(r["real_majority_raw"] for r in el if not r["dissolved"]),
            "eligible_surviving_real_majority_canon": sum(r["real_majority_canon"] for r in el if not r["dissolved"]),
            "decisive_surviving_real_majority_raw": sum(r["real_majority_raw"] for r in de if not r["dissolved"]),
            "decisive_surviving_real_majority_canon": sum(r["real_majority_canon"] for r in de if not r["dissolved"]),
        }
    return agg, rows, merges


def write_csv(path, rows):
    if not rows:
        path.write_text("")
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def canon_map(data, dsname):
    rows = []
    for q, resps, tag in data:
        for c in ORIG["build_contribs"](q, resps):
            co = C.canon(c["object"])
            rows.append({"dataset": dsname, "question": q["id"], "contribution_id": c["_id"],
                         "raw_object": c["object"], "canonical_object": co,
                         "rust_normalize_raw": C.rust_normalize_object(c["object"]),
                         "changed_vs_rust_normalize": int(co != C.rust_normalize_object(c["object"]))})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", required=True)
    ap.add_argument("--bootstrap", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--datasets", nargs="*", default=["v3", "v1orig"])
    ap.add_argument("--modes", nargs="*", default=["raw", "canon"])
    args = ap.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    binhash = hashlib.sha256(open(args.bin, "rb").read()).hexdigest()
    seal = {"canon_version": C.CANON_VERSION,
            "canon_py_sha256": hashlib.sha256((HERE / "canon.py").read_bytes()).hexdigest(),
            "run_canon_py_sha256": hashlib.sha256((HERE / "run_canon.py").read_bytes()).hexdigest(),
            "evaluate_v3_py_sha256": hashlib.sha256((EVAL / "v3" / "evaluate_v3.py").read_bytes()).hexdigest(),
            "binary": args.bin, "binary_sha256": binhash,
            "bootstrap": args.bootstrap, "seed": args.seed,
            "synonyms": {k: {"to": " ".join(v), "source": C.SYNONYM_SOURCES[k]} for k, v in C.SYNONYMS.items()},
            "policy_incompatible_values_canon": None}
    res = {"seal": seal, "structure": {}, "modes": {}}
    for ds in args.datasets:
        data = e3.load_dataset(ds)
        agg, rows, merges = structure_stats(ds, data)
        res["structure"][ds] = agg
        write_csv(RESULTS / f"conflict_sets_raw_vs_canon_{ds}.csv", rows)
        write_csv(RESULTS / f"merge_audit_{ds}.csv", merges)
        write_csv(RESULTS / f"canon_map_{ds}.csv", canon_map(data, ds))
    for mode in args.modes:
        set_mode(mode)
        if mode == "canon":
            seal["policy_incompatible_values_canon"] = e3.DEFAULT_POLICY["values"]["incompatible_values"]
        res["modes"][mode] = {}
        for ds in args.datasets:
            data = e3.load_dataset(ds)
            s = e3.analyse(ds, data, args.bin, args)
            s["native_policy_hash"] = json.load(open(next((e3.OUT / "rust" / ds).glob("*/native.out.json"))))["policy_hash"]
            res["modes"][mode][ds] = s
            print(f"[{mode}/{ds}] done", file=sys.stderr)
    set_mode("raw")
    json.dump(res, open(RESULTS / "evaluation_canon.json", "w"), indent=2)
    print(json.dumps(res["structure"], indent=1))


if __name__ == "__main__":
    main()
