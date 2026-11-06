#!/usr/bin/env python3
"""Text-dedup sensitivity for the 0.2.0 FEVER fresh2 validation. No checker calls: re-scores
validation/results/fresh2_fever-<checker_id>.jsonl after dropping pairs whose claim text equals
(NFKC, casefold, whitespace-collapsed, trailing period dropped) a claim elsewhere.

Variants:
  disclosed   the 5 pairs in real-agent-eval/v5/benchmark/exclusion_proofs.json
              disclosed_not_required_zero.same_text_collisions_with_later_validation_slices
  items       text-equal to any v5 item (dev + confirmatory), any v4 FEVER item, or a disclosed pair
  strict      'items' plus text-equal to any v5 reserve_order FEVER claim or any claim of the first
              FEVER slice (the development slice); within-slice repeats collapsed to the lowest id

Writes validation/<checker_id>.dedup.json (the main report is frozen and left untouched).
Run: python3 -I tools/evidence/support/validation/dedup_v2.py
"""

import json
import os
import re
import sys
import unicodedata

VDIR = os.path.dirname(os.path.abspath(__file__))
SUP = os.path.dirname(VDIR)
ROOT = os.path.abspath(os.path.join(SUP, "..", "..", ".."))
sys.path[:0] = [SUP, os.path.dirname(SUP)]
import validate as VA  # noqa: E402
from canonical import sha256_hex  # noqa: E402

CHECKER_ID = "f2a14bd8988371bd231ca6ff137be13e"
V5B = os.path.join(ROOT, "real-agent-eval", "v5", "benchmark")
V4B = os.path.join(ROOT, "real-agent-eval", "v4", "benchmark")


def norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s).casefold()).strip().rstrip(".").strip()


def find_key(o, key):
    if isinstance(o, dict):
        if key in o:
            return o[key]
        for v in o.values():
            r = find_key(v, key)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = find_key(v, key)
            if r is not None:
                return r
    return None


def main():
    sl = VA._jsonl(os.path.join(VDIR, "fever_slice_fresh2.jsonl"))
    res_p = os.path.join(VDIR, "results", "fresh2_fever-%s.jsonl" % CHECKER_ID)
    res_rows = VA._jsonl(res_p)  # file order, so 'original' reproduces the report's bootstrap CIs
    res = {r["id"]: r for r in res_rows}
    claim = {r["id"]: r["claim"] for r in sl}
    pdev = {d["id"]: d["claim"] for d in VA._jsonl(os.path.join(V4B, "downloads", "fever", "paper_dev.jsonl"))}

    proofs_p = os.path.join(V5B, "exclusion_proofs.json")
    disc = find_key(json.load(open(proofs_p)), "disclosed_not_required_zero")["same_text_collisions_with_later_validation_slices"]
    disc_pairs = [p for p in disc["pairs"] if p["slice"] == "fever_slice_fresh2.jsonl"]
    disclosed = {p["slice_id"] for p in disc_pairs}
    for p in disc_pairs:  # verify the disclosure against the slice text
        assert norm(claim[p["slice_id"]]) == norm(p["text"]), p

    items_txt, reserve_txt = set(norm(p["text"]) for p in disc_pairs), set()
    for f in ("items_dev.jsonl", "items_confirmatory.jsonl"):
        for d in VA._jsonl(os.path.join(V5B, f)):
            if d["source"]["key"] == "fever" and int(d["source"]["source_id"]) in pdev:
                items_txt.add(norm(pdev[int(d["source"]["source_id"])]))
        for d in VA._jsonl(os.path.join(V4B, f)):
            if d["id"].startswith("v4-fever") and int(d["id"][len("v4-fever"):]) in pdev:
                items_txt.add(norm(pdev[int(d["id"][len("v4-fever"):])]))
    for rid in json.load(open(os.path.join(V5B, "reserve_order.json")))["reserve"]["fever"]:
        i = int(rid[len("v5-fever"):])
        if i in pdev:
            reserve_txt.add(norm(pdev[i]))
    dev_txt = {norm(r["claim"]) for r in VA._jsonl(os.path.join(VDIR, "fever_slice.jsonl"))}

    drop_items = {i for i in claim if i in disclosed or norm(claim[i]) in items_txt}
    drop_strict = set(drop_items) | {i for i in claim if norm(claim[i]) in reserve_txt or norm(claim[i]) in dev_txt}
    seen = {}
    for i in sorted(claim, key=lambda x: int(x[len("fever"):])):
        if i in drop_strict:
            continue
        t = norm(claim[i])
        if t in seen:
            drop_strict.add(i)
        else:
            seen[t] = i
    dev_overlap = sorted(i for i in claim if norm(claim[i]) in dev_txt)

    def score(drop):
        rows = [r for r in res_rows if r["id"] not in drop]
        m = VA.metrics(rows)
        pc = m["per_class"]
        return {"n": m["n"], "dropped": len(drop),
                "dropped_by_gold": {g: sum(1 for i in drop if res[i]["gold"] == g) for g in ("supports", "refutes", "not_enough_info")},
                "dropped_predicted_refutes": sum(1 for i in drop if res[i]["label"] == "refutes"),
                "macro_f1": m["macro_f1"], "macro_f1_bootstrap95": m["macro_f1_bootstrap95"],
                "refutes_precision": pc["refutes"]["precision"],
                "refutes_precision_bootstrap95": pc["refutes"]["precision_bootstrap95"],
                "refutes_precision_wilson95": pc["refutes"]["precision_wilson95"],
                "refutes_tp_fp": [pc["refutes"]["tp"], pc["refutes"]["fp"]],
                "supports_precision": pc["supports"]["precision"],
                "supports_precision_bootstrap95": pc["supports"]["precision_bootstrap95"],
                "accuracy": m["accuracy"], "confusion_gold_by_pred": m["confusion_gold_by_pred"],
                "pass_point": {"macro_f1": m["macro_f1"] >= VA.THRESHOLDS["macro_f1"],
                               "refutes_precision": pc["refutes"]["precision"] >= VA.THRESHOLDS["refutes_precision"]},
                "pass_ci_lower": {"macro_f1": m["macro_f1_bootstrap95"][0] >= VA.THRESHOLDS["macro_f1"],
                                  "refutes_precision": pc["refutes"]["precision_bootstrap95"][0] >= VA.THRESHOLDS["refutes_precision"]}}

    rep = {"format": "bran-support-validation/dedup/1", "checker_id": CHECKER_ID,
           "no_new_checker_calls": True,
           "normalisation": "NFKC, casefold, whitespace collapsed, trailing period dropped",
           "inputs": {"results": os.path.relpath(res_p, ROOT), "results_sha256": sha256_hex(open(res_p, "rb").read()),
                      "slice_sha256": sha256_hex(open(os.path.join(VDIR, "fever_slice_fresh2.jsonl"), "rb").read()),
                      "exclusion_proofs": os.path.relpath(proofs_p, ROOT)},
           "original": score(set()),
           "variants": {
               "disclosed": dict(score(disclosed), ids=sorted(disclosed),
                                 rule="the 5 disclosed same-text collisions with v5 items (4 collected, 1 extension)"),
               "items": dict(score(drop_items), ids=sorted(drop_items),
                             rule="text-equal to any v5 item, v4 FEVER item, or disclosed pair"),
               "strict": dict(score(drop_strict), rule="items + text-equal to any v5 reserve FEVER claim or first-slice "
                                                        "(development) claim + within-slice repeats collapsed"),
           },
           "development_slice_text_overlap": {"n": len(dev_overlap), "ids": dev_overlap,
                                              "claims": [claim[i] for i in dev_overlap]}}
    p = os.path.join(VDIR, "%s.dedup.json" % CHECKER_ID)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1, sort_keys=True)
        fh.write("\n")
    for k in ("original",):
        print(k, {x: rep[k][x] for x in ("n", "macro_f1", "macro_f1_bootstrap95", "refutes_precision",
                                          "refutes_precision_bootstrap95", "supports_precision", "supports_precision_bootstrap95")})
    for k, v in rep["variants"].items():
        print(k, {x: v[x] for x in ("n", "dropped_by_gold", "dropped_predicted_refutes", "macro_f1", "macro_f1_bootstrap95",
                                     "refutes_precision", "refutes_precision_bootstrap95", "refutes_precision_wilson95",
                                     "refutes_tp_fp", "supports_precision", "supports_precision_bootstrap95")})
    print("dev overlap", rep["development_slice_text_overlap"])
    print(p)


if __name__ == "__main__":
    main()
