#!/usr/bin/env python3
"""
Eval v6 secondary grader G-AK+A (PREREGISTRATION.md section 3.1): builds items_confirmatory_aliases.jsonl.

The output is the v5 confirmatory item file with only `gold.aliases` extended, on PopQA items, by the list for that item in
v6/tuning/aliases/aliases.json (union, original aliases first, then the added ones in file order). Every other line is copied
byte for byte; changed lines are written in the input's own format (json.dumps(ensure_ascii=False, sort_keys=True) + "\\n").
Deterministic. No model, hosted or network call.

Asserts: input sha256 38987c42...1a83, aliases sha256 77d1fce0...2ca4 (and aliases.json.sha256), and the gold-consistency
check on all 1,100 items:
  * nothing but gold.aliases of PopQA items differs from the input (compared as parsed JSON, per item);
  * the original aliases are a prefix of the new ones; only PopQA ids appear in aliases.json;
  * under the frozen grader (answer_key.grade, evaluate_v5.grade_value) every item's gold answer and every alias, original or
    added, grades correct against its own item (entity: raw line = the alias text; letter / supported_refuted: the gold answer);
  * no added alias is also an alias of another PopQA item that shares the subject (the builder's own conflict rule, re-checked).

Usage
  build_alias_items_v6.py --items v5/benchmark/items_confirmatory.jsonl --aliases v6/tuning/aliases/aliases.json
                          --out v6/results/items_confirmatory_aliases.jsonl
"""
import argparse
import hashlib
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
V6 = Path(__file__).resolve().parent
V5 = V6.parent / "v5"
ITEMS_SHA256 = "38987c422cd1655a901c00710f0bfb948ba41540efc61ed19b06b22c3e4c1a83"
ALIASES_SHA256 = "77d1fce09c137647eea4a12b85dfc574d493e86fe9f79f2d1d653bb8b4ca2174"


def _load_e():
    if "evaluate_v5" in sys.modules:
        return sys.modules["evaluate_v5"]
    spec = importlib.util.spec_from_file_location("evaluate_v5", V5 / "evaluate_v5.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["evaluate_v5"] = mod
    spec.loader.exec_module(mod)
    return mod


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def norm(s):
    return " ".join(s.lower().strip().split())


def dump_line(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n"


def build(items_path, aliases_path):
    """-> (output text, report). Raises SystemExit on any failed assertion."""
    E = _load_e()
    if sha256_file(items_path) != ITEMS_SHA256:
        raise SystemExit(f"ABORT: {items_path} is not the frozen item file (sha256 {ITEMS_SHA256[:8]}...)")
    if sha256_file(aliases_path) != ALIASES_SHA256:
        raise SystemExit(f"ABORT: {aliases_path} is not the frozen alias list (sha256 {ALIASES_SHA256[:8]}...)")
    side = Path(str(aliases_path) + ".sha256")
    if side.exists() and side.read_text().split()[0] != ALIASES_SHA256:
        raise SystemExit("ABORT: aliases.json.sha256 disagrees with the preregistered hash")
    aliases = json.load(open(aliases_path))
    lines = open(items_path, encoding="utf-8").read().splitlines(keepends=True)
    out, orig, aug = [], {}, {}
    for line in lines:
        x = json.loads(line)
        iid = x["id"]
        orig[iid] = x
        add = aliases.get(iid)
        if add and x["source"]["key"] == "popqa":
            y = json.loads(line)
            have = list(y["gold"]["aliases"])
            seen = {a for a in have}
            for a in add:
                if a not in seen:
                    have.append(a)
                    seen.add(a)
            y["gold"]["aliases"] = have
            aug[iid] = y
            out.append(dump_line(y))
        else:
            aug[iid] = x
            out.append(line if line.endswith("\n") else line + "\n")
    errs = []
    unknown = sorted(set(aliases) - set(orig))
    non_popqa = sorted(i for i in aliases if i in orig and orig[i]["source"]["key"] != "popqa")
    if unknown or non_popqa:
        errs.append(f"aliases.json ids unknown {unknown[:3]} or not PopQA {non_popqa[:3]}")
    n_changed = n_added = 0
    for iid, x in orig.items():
        y = aug[iid]
        a0, a1 = x["gold"].get("aliases", []), y["gold"].get("aliases", [])
        if a1[:len(a0)] != a0:
            errs.append(f"{iid}: original aliases are not a prefix")
        strip = lambda z: {k: (v if k != "gold" else {kk: vv for kk, vv in v.items() if kk != "aliases"}) for k, v in z.items()}
        if strip(x) != strip(y):
            errs.append(f"{iid}: a field other than gold.aliases differs")
        if a1 != a0:
            n_changed += 1
            n_added += len(a1) - len(a0)
        # the frozen grader accepts the gold answer and every alias on the item's own record
        if x["answer_format"] == "entity":
            texts = [y["gold"]["answer"]] + list(a1)
            for t in texts:
                c = E.C.canon(" ".join(t.split()))
                if not c or not E.grade_value(y, c, t):
                    errs.append(f"{iid}: gold text {t!r} does not grade correct under G-AK+A")
        else:
            if not E.grade_value(y, y["gold"]["answer"], y["gold"]["answer"]):
                errs.append(f"{iid}: gold answer does not grade correct")
    # an added alias must not be a gold alias of another PopQA item with the same subject
    by_subj = defaultdict(list)
    for iid, y in aug.items():
        if y["source"]["key"] == "popqa":
            by_subj[y["source"].get("subj")].append(iid)
    for subj, ids in by_subj.items():
        if len(ids) < 2:
            continue
        for i in ids:
            added = {norm(a) for a in aug[i]["gold"]["aliases"]} - {norm(a) for a in orig[i]["gold"]["aliases"]}
            for j in ids:
                if j != i and added & {norm(a) for a in aug[j]["gold"]["aliases"]}:
                    errs.append(f"{i}: an added alias is also an alias of {j} (same subject)")
    if errs:
        raise SystemExit("ABORT: gold-consistency check failed: " + "; ".join(errs[:8]) + f" ({len(errs)} problems)")
    text = "".join(out)
    rep = {"items": len(orig), "popqa_items_changed": n_changed, "aliases_added": n_added,
           "aliases_file_entries": len(aliases), "aliases_file_total": sum(len(v) for v in aliases.values()),
           "items_sha256": ITEMS_SHA256, "aliases_sha256": ALIASES_SHA256,
           "output_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "gold_consistency": "passed on all items"}
    return text, rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="eval v6 alias items (G-AK+A)")
    ap.add_argument("--items", default=str(V5 / "benchmark" / "items_confirmatory.jsonl"))
    ap.add_argument("--aliases", default=str(V6 / "tuning" / "aliases" / "aliases.json"))
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out = Path(a.out).resolve()
    if V5 in out.parents or V6 not in out.parents:
        raise SystemExit(f"ABORT: --out must be under {V6} (never under v5)")
    text, rep = build(a.items, a.aliases)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
