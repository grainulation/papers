#!/usr/bin/env python3
"""
Validate the automatic graders against human labels and re-score the headline tables.

Usage
  python3 analyze.py labels_aid.csv [labels_second.csv ...] [--primary aid] [--boot 2000] [--seed 42]
                     [--include-post-reveal] [--out analysis.md]

Inputs: sample.json (from sample.py) and one or more CSVs exported by label.html.
Output: a Markdown report (stdout, and --out if given) plus analysis.json next to it.

Sections
  1 coverage           labeled items per labeler and stratum
  2 agreement          Cohen's kappa human vs each grader (and heuristic garbage flag vs well_formed),
                       human vs human; item bootstrap 95% CI (stratified by sampling stratum)
  3 grader P/R         precision / recall of each grader against human matches_gold
                       (sample, and population-weighted with the N_h/n_h stratum weights)
  4 headline re-score  Tables A/B for v3 and v1orig with member correctness from human labels
                       (matches_gold == yes; sensitivity: correct == true)
  5 precision sheets   human category breakdown of the Rust-admitted claims that fail the stricter
                       grader, post-stratified by heuristic category onto the sheets' row counts

Standard library only. The primary labeler's labels drive sections 2-5; other labelers enter only
the human-vs-human agreement.
"""

import argparse
import csv
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIELDS = ["correct", "matches_gold", "well_formed_extraction"]
VALID = {"correct": {"true", "false", "partially", "unclear"},
         "matches_gold": {"yes", "no"}, "well_formed_extraction": {"yes", "no"}}
HUMAN_CATS = ["grader-miss", "extra-but-true", "extraction-garbage", "incorrect", "partially", "unclear"]


# ── statistics ──────────────────────────────────────────────────

def kappa(pairs, weights=None):
    """Cohen's kappa for a list of (a, b) labels, optionally weighted."""
    if not pairs:
        return float("nan")
    w = weights or [1.0] * len(pairs)
    tot = sum(w)
    cats = sorted({x for p in pairs for x in p})
    po = sum(wi for (a, b), wi in zip(pairs, w) if a == b) / tot
    pa = {c: sum(wi for (a, _), wi in zip(pairs, w) if a == c) / tot for c in cats}
    pb = {c: sum(wi for (_, b), wi in zip(pairs, w) if b == c) / tot for c in cats}
    pe = sum(pa[c] * pb[c] for c in cats)
    if pe >= 1.0 - 1e-12:
        return 1.0 if po >= 1.0 - 1e-12 else float("nan")
    return (po - pe) / (1 - pe)


def pr(pairs, weights=None):
    """pairs = (human, grader) booleans. Returns precision, recall, tp, fp, fn, tn (weighted)."""
    w = weights or [1.0] * len(pairs)
    tp = sum(wi for (h, g), wi in zip(pairs, w) if h and g)
    fp = sum(wi for (h, g), wi in zip(pairs, w) if not h and g)
    fn = sum(wi for (h, g), wi in zip(pairs, w) if h and not g)
    tn = sum(wi for (h, g), wi in zip(pairs, w) if not h and not g)
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    return prec, rec, tp, fp, fn, tn


def boot(rows, stat, strata, n, seed):
    """Stratified item bootstrap: resample rows within each stratum. Returns (lo, hi) 95%."""
    by = defaultdict(list)
    for r, s in zip(rows, strata):
        by[s].append(r)
    rng = random.Random(seed)
    vals = []
    for _ in range(n):
        res = []
        for s in sorted(by):
            g = by[s]
            res.extend(rng.choice(g) for _ in g)
        v = stat(res)
        if not math.isnan(v):
            vals.append(v)
    if not vals:
        return float("nan"), float("nan")
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[min(len(vals) - 1, int(0.975 * len(vals)))]


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def cluster_boot(rows, a, b, n, seed):
    by_q = defaultdict(list)
    for r in rows:
        by_q[r["question"]].append(r)
    qids = sorted(by_q)
    if not qids:
        return float("nan"), float("nan"), float("nan")
    rng = random.Random(seed)
    diffs = []
    for _ in range(n):
        s = [rng.choice(qids) for _ in qids]
        m = sum(len(by_q[x]) for x in s)
        diffs.append(sum(r[a] - r[b] for x in s for r in by_q[x]) / m)
    diffs.sort()
    point = sum(r[a] - r[b] for r in rows) / len(rows)
    return point, diffs[int(0.025 * n)], diffs[min(n - 1, int(0.975 * n))]


def f(x, d=3):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{d}f}"


# ── loading ─────────────────────────────────────────────────────

def load_labels(paths, sha, include_post_reveal, notes):
    out = {}   # labeler -> item_id -> row
    for p in paths:
        rows = list(csv.DictReader(open(p, newline="")))
        for r in rows:
            lid = (r.get("labeler_id") or Path(p).stem).strip()
            if r.get("sample_sha") and r["sample_sha"] != sha:
                notes.append(f"WARNING {p}: sample_sha {r['sample_sha']} != sample.json {sha}; rows used by item_id")
            if not all(r.get(k, "").strip() for k in FIELDS):
                continue
            bad = [k for k in FIELDS if r[k].strip() not in VALID[k]]
            if bad:
                notes.append(f"WARNING {p} item {r['item_id']}: invalid value in {bad}; row skipped")
                continue
            if r.get("edited_after_reveal", "0") in ("1", "true") and not include_post_reveal:
                notes.append(f"{lid}: item {r['item_id']} edited after reveal; excluded (use --include-post-reveal)")
                continue
            out.setdefault(lid, {})[r["item_id"]] = {k: r[k].strip() for k in FIELDS} | {"notes": r.get("notes", "")}
    return out


def human_category(l):
    if l["well_formed_extraction"] == "no":
        return "extraction-garbage"
    if l["matches_gold"] == "yes":
        return "grader-miss"
    return {"true": "extra-but-true", "false": "incorrect"}.get(l["correct"], l["correct"])


# ── sections ────────────────────────────────────────────────────

def section_agreement(items, L, others, args, rep, res):
    lab = [it for it in items if it["item_id"] in L]
    strata = [it["stratum"] for it in lab]
    w = [it["weight"] for it in lab]
    rep.append("## 2. Agreement (Cohen's kappa, 95% stratified bootstrap CI)\n")
    rep.append("Human = primary labeler's `matches_gold`; grader = the grader's verdict on the same claim "
               "(any gold triple). 'weighted' uses the N_h/n_h stratum weights (population of all "
               "distinct claims in v3 + v1orig).\n")
    rep.append("| comparison | n | kappa (sample) | 95% CI | kappa (weighted) | 95% CI | raw agreement |")
    rep.append("|---|---|---|---|---|---|---|")
    res["kappa"] = {}
    comps = [("human matches_gold vs v1 grader", lambda it, l: (l["matches_gold"] == "yes", it["grader"]["v1_match"])),
             ("human matches_gold vs v2 grader", lambda it, l: (l["matches_gold"] == "yes", it["grader"]["v2_match"])),
             ("human well_formed=no vs heuristic extraction-garbage",
              lambda it, l: (l["well_formed_extraction"] == "no", it["grader"]["heuristic_category"] == "extraction-garbage"))]
    for name, fn in comps:
        rows = [(fn(it, L[it["item_id"]]), it["weight"]) for it in lab]
        pairs = [r[0] for r in rows]
        k = kappa(pairs)
        lo, hi = boot(rows, lambda rs: kappa([x[0] for x in rs]), strata, args.boot, args.seed)
        kw = kappa(pairs, w)
        wlo, whi = boot(rows, lambda rs: kappa([x[0] for x in rs], [x[1] for x in rs]), strata, args.boot, args.seed)
        agree = sum(a == b for a, b in pairs) / len(pairs) if pairs else float("nan")
        rep.append(f"| {name} | {len(pairs)} | {f(k)} | [{f(lo)}, {f(hi)}] | {f(kw)} | [{f(wlo)}, {f(whi)}] | {f(agree)} |")
        res["kappa"][name] = {"n": len(pairs), "kappa": k, "ci": [lo, hi], "kappa_weighted": kw, "ci_weighted": [wlo, whi]}
    # subset: well-formed extractions only
    wf = [it for it in lab if L[it["item_id"]]["well_formed_extraction"] == "yes"]
    for g in ["v1", "v2"]:
        pairs = [(L[it["item_id"]]["matches_gold"] == "yes", it["grader"][f"{g}_match"]) for it in wf]
        rows = [(p, 1.0) for p in pairs]
        lo, hi = boot(rows, lambda rs: kappa([x[0] for x in rs]), [it["stratum"] for it in wf], args.boot, args.seed)
        rep.append(f"| human vs {g} grader, well-formed extractions only | {len(pairs)} | {f(kappa(pairs))} | "
                   f"[{f(lo)}, {f(hi)}] | | | {f(sum(a == b for a, b in pairs) / len(pairs) if pairs else float('nan'))} |")
    rep.append("")

    if others:
        rep.append("### Human vs human\n")
        rep.append("| labelers | field | n common | kappa | 95% CI | raw agreement |")
        rep.append("|---|---|---|---|---|---|")
        res["human_human"] = []
        all_l = [(args.primary, L)] + others
        for i in range(len(all_l)):
            for j in range(i + 1, len(all_l)):
                (na, A), (nb, B) = all_l[i], all_l[j]
                common = [it for it in items if it["item_id"] in A and it["item_id"] in B]
                for fld in FIELDS:
                    pairs = [(A[it["item_id"]][fld], B[it["item_id"]][fld]) for it in common]
                    rows = [(p, 1.0) for p in pairs]
                    lo, hi = boot(rows, lambda rs: kappa([x[0] for x in rs]), [it["stratum"] for it in common],
                                  args.boot, args.seed)
                    ag = sum(a == b for a, b in pairs) / len(pairs) if pairs else float("nan")
                    rep.append(f"| {na} vs {nb} | {fld} | {len(pairs)} | {f(kappa(pairs))} | [{f(lo)}, {f(hi)}] | {f(ag)} |")
                    res["human_human"].append({"a": na, "b": nb, "field": fld, "n": len(pairs),
                                               "kappa": kappa(pairs), "ci": [lo, hi]})
        rep.append("")


def section_pr(items, L, args, rep, res):
    lab = [it for it in items if it["item_id"] in L]
    strata = [it["stratum"] for it in lab]
    rep.append("## 3. Grader precision / recall against human `matches_gold`\n")
    rep.append("| grader | weighting | precision | 95% CI | recall | 95% CI | TP | FP | FN | TN |")
    rep.append("|---|---|---|---|---|---|---|---|---|---|")
    res["grader_pr"] = {}
    for g in ["v1", "v2"]:
        rows = [((L[it["item_id"]]["matches_gold"] == "yes", it["grader"][f"{g}_match"]), it["weight"]) for it in lab]
        for wname, use_w in [("sample", False), ("weighted", True)]:
            def st(rs, k):
                return pr([x[0] for x in rs], [x[1] for x in rs] if use_w else None)[k]
            p_, r_, tp, fp, fn, tn = pr([x[0] for x in rows], [x[1] for x in rows] if use_w else None)
            plo, phi = boot(rows, lambda rs: st(rs, 0), strata, args.boot, args.seed)
            rlo, rhi = boot(rows, lambda rs: st(rs, 1), strata, args.boot, args.seed)
            d = 0 if not use_w else 1
            rep.append(f"| {g} | {wname} | {f(p_)} | [{f(plo)}, {f(phi)}] | {f(r_)} | [{f(rlo)}, {f(rhi)}] | "
                       f"{f(tp, d)} | {f(fp, d)} | {f(fn, d)} | {f(tn, d)} |")
            res["grader_pr"][f"{g}|{wname}"] = {"precision": p_, "precision_ci": [plo, phi], "recall": r_,
                                                "recall_ci": [rlo, rhi], "tp": tp, "fp": fp, "fn": fn, "tn": tn}
    rep.append("")
    rep.append("### Per stratum (sample counts)\n")
    rep.append("| stratum | weight | n labeled | human yes | v1 yes | v2 yes | v1 agrees | v2 agrees | well-formed yes | correct=true |")
    rep.append("|---|---|---|---|---|---|---|---|---|---|")
    by = defaultdict(list)
    for it in lab:
        by[it["stratum"]].append(it)
    for s in sorted(by):
        xs = by[s]
        hy = [L[i["item_id"]]["matches_gold"] == "yes" for i in xs]
        rep.append(f"| {s} | {round(xs[0]['weight'], 2)} | {len(xs)} | {sum(hy)} | "
                   f"{sum(i['grader']['v1_match'] for i in xs)} | {sum(i['grader']['v2_match'] for i in xs)} | "
                   f"{sum(h == i['grader']['v1_match'] for h, i in zip(hy, xs))} | "
                   f"{sum(h == i['grader']['v2_match'] for h, i in zip(hy, xs))} | "
                   f"{sum(L[i['item_id']]['well_formed_extraction'] == 'yes' for i in xs)} | "
                   f"{sum(L[i['item_id']]['correct'] == 'true' for i in xs)} |")
    rep.append("")
    # disagreements worth discussing
    dis = [it for it in lab if (L[it["item_id"]]["matches_gold"] == "yes") != it["grader"]["v2_match"]]
    rep.append(f"Items where the human and the stricter grader disagree: {len(dis)} "
               f"(listed in analysis.json under `v2_disagreements`).\n")
    res["v2_disagreements"] = [{"item_id": it["item_id"], "question_id": it["question_id"],
                                "claim_text": it["claim_text"], "triple": it["triple"],
                                "human": L[it["item_id"]], "v1": it["grader"]["v1_match"],
                                "v2": it["grader"]["v2_match"], "v2_reason": it["grader"]["v2_reason"]} for it in dis]


def score_tables(conflicts, flag_of, args):
    """flag_of(item_id) -> bool or None (unlabeled). Returns {(ds, table): stats}."""
    out = {}
    groups = defaultdict(list)
    for cf in conflicts:
        groups[(cf["dataset"], cf["table"])].append(cf)
    for key, cfs in sorted(groups.items()):
        rows, unlabeled, missed = [], 0, 0
        methods = list(cfs[0]["outputs"].keys())
        for cf in cfs:
            fl = [flag_of(i) if i else None for i in cf["members"]]
            if any(x is None for x in fl):
                unlabeled += 1
                if any(x for x in fl if x is not None):
                    missed += 1
                continue
            if not any(fl):
                continue
            fmap = dict(zip(cf["members"], fl))
            row = {"question": cf["question_id"], "decisive": int(not all(fl))}
            for m in methods:
                o = cf["outputs"][m]
                row[m] = int(bool(o) and all(fmap.get(i, False) for i in o))
            rows.append(row)
        dec = [r for r in rows if r["decisive"]]
        st = {"sets_total": len(cfs), "sets_not_fully_labeled": unlabeled,
              "not_fully_labeled_with_a_labeled_yes_member": missed,
              "eligible": len(rows), "decisive": len(dec), "methods": {}}
        for m in methods:
            b = sum(1 for r in rows if r[m] and not r["majority"])
            c = sum(1 for r in rows if r["majority"] and not r[m])
            st["methods"][m] = {"eligible_correct": sum(r[m] for r in rows),
                                "decisive_correct": sum(r[m] for r in dec),
                                "b": b, "c": c, "p": mcnemar_exact(b, c)}
        st["boot_all"] = cluster_boot(rows, "rust", "majority", args.boot, args.seed) if rows else None
        st["boot_decisive"] = cluster_boot(dec, "rust", "majority", args.boot, args.seed) if dec else None
        out[key] = st
    return out


def section_tables(sample, L, args, rep, res):
    items = {it["item_id"]: it for it in sample["items"]}
    conflicts = sample["conflicts"]
    variants = [
        ("human matches_gold", lambda i: (L[i]["matches_gold"] == "yes") if i in L else None),
        ("human correct == true (sensitivity)", lambda i: (L[i]["correct"] == "true") if i in L else None),
        ("v1 grader (reproduction, same sets)", lambda i: items[i]["grader"]["v1_match"] if i in items else None),
        ("v2 grader (reproduction, same sets)", lambda i: items[i]["grader"]["v2_match"] if i in items else None),
    ]
    rep.append("## 4. Headline tables re-scored with human labels\n")
    rep.append("A set counts only when every member is labeled. Eligible = some member correct; decisive = "
               "eligible and some member incorrect. A method is correct iff it outputs at least one member and "
               "every output member is correct (dissolved Table A sets with no admitted member are wrong). "
               "The two grader rows use only labeled items, so they reproduce RESULTS.md only when the "
               "relevant sets are fully labeled. Sets that no grader marked eligible were not sampled in "
               "full; `missed` counts such sets in which some labeled member is human-correct (a lower "
               "bound on sets the graders made ineligible).\n")
    res["tables"] = {}
    for vname, flag in variants:
        st = score_tables(conflicts, flag, args)
        res["tables"][vname] = {f"{k[0]}|{k[1]}": v for k, v in st.items()}
        rep.append(f"### {vname}\n")
        for (ds, t), s in st.items():
            rep.append(f"**{ds}, Table {t}** ({'Python-harness slots, Rust forced policy' if t == 'A' else 'Rust-native slots'}): "
                       f"eligible {s['eligible']}, decisive {s['decisive']}; sets {s['sets_total']}, "
                       f"not fully labeled {s['sets_not_fully_labeled']}, missed {s['not_fully_labeled_with_a_labeled_yes_member']}.\n")
            if not s["eligible"]:
                continue
            rep.append("| method | eligible correct | decisive correct | vs majority b/c | exact McNemar p |")
            rep.append("|---|---|---|---|---|")
            for m, v in s["methods"].items():
                bc = "—" if m == "majority" else f"{v['b']}/{v['c']}"
                p = "—" if m == "majority" else f"{v['p']:.4g}"
                rep.append(f"| {m} | {v['eligible_correct']}/{s['eligible']} | {v['decisive_correct']}/{s['decisive']} | {bc} | {p} |")
            for nm, bt in [("all eligible", s["boot_all"]), ("decisive", s["boot_decisive"])]:
                if bt:
                    rep.append(f"\nRust − majority, {nm}: {f(bt[0], 4)}, 95% question-cluster CI [{f(bt[1], 4)}, {f(bt[2], 4)}]")
            rep.append("")


def section_precision(sample, L, rep, res):
    rep.append("## 5. Precision adjudication (Rust-admitted claims failing the stricter grader)\n")
    rep.append("Human category: `extraction-garbage` if well_formed_extraction = no; else `grader-miss` if "
               "matches_gold = yes; else `extra-but-true` / `incorrect` / `partially` / `unclear` from `correct`. "
               "Estimated rows = for each heuristic category, the human-category shares among labeled claims in "
               "that sheet and category (each claim weighted by its stratum weight × its rows in the sheet), "
               "times the sheet's row count for that category (post-stratification).\n")
    res["precision"] = {}
    names = {"v3": "v3/results/precision_adjudication_v3.csv (Rust, v3 responses)",
             "v1orig": "v3/results/precision_adjudication_v1orig.csv (Rust, original v1 responses)",
             "v2python": "results/precision_adjudication.csv (Python reducer, original v1 responses)"}
    for sheet, desc in names.items():
        tot = sample["sheet_totals"][sheet]
        cells = defaultdict(Counter)
        wcells = defaultdict(lambda: defaultdict(float))
        for it in sample["items"]:
            n = it["grader"]["sheet_rows"].get(sheet, 0)
            if not n or it["item_id"] not in L:
                continue
            hc, hcat = it["grader"]["heuristic_category"], human_category(L[it["item_id"]])
            cells[hc][hcat] += 1
            wcells[hc][hcat] += it["weight"] * n
        rep.append(f"### {desc}: {tot['rows']} rows\n")
        rep.append("| heuristic | rows | labeled claims | " + " | ".join(HUMAN_CATS) + " |")
        rep.append("|---|---|---|" + "---|" * len(HUMAN_CATS))
        est = Counter()
        for hc, rows in sorted(tot["by_heuristic"].items()):
            c = cells.get(hc, Counter())
            wsum = sum(wcells[hc].values())
            for k in HUMAN_CATS:
                if wsum:
                    est[k] += rows * wcells[hc][k] / wsum
            if not wsum:
                est["(unlabeled)"] += rows
            rep.append(f"| {hc} | {rows} | {sum(c.values())} | " + " | ".join(str(c.get(k, 0)) for k in HUMAN_CATS) + " |")
        rep.append("")
        rep.append("Estimated rows by human category: " +
                   ", ".join(f"{k} {est[k]:.0f}" for k in HUMAN_CATS + ["(unlabeled)"] if est[k]) + ".")
        if sheet in sample["admitted_total"]:
            adm = sample["admitted_total"][sheet]
            passing = adm - tot["rows"]
            rep.append(f"Admitted {adm}; passing the stricter grader {passing}. Adjusted precision "
                       f"(passing + estimated grader-miss) / admitted = {(passing + est['grader-miss']) / adm:.3f}; "
                       f"counting extra-but-true as well: {(passing + est['grader-miss'] + est['extra-but-true']) / adm:.3f}. "
                       "This assumes every passing claim is a true match; section 3's grader precision tests that.")
        rep.append("")
        res["precision"][sheet] = {"cells": {k: dict(v) for k, v in cells.items()}, "estimated_rows": dict(est)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("labels", nargs="+", help="label CSVs exported by label.html")
    ap.add_argument("--sample", default=str(HERE / "sample.json"))
    ap.add_argument("--primary", help="labeler id whose labels drive sections 2-5 (default: first CSV's)")
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--include-post-reveal", action="store_true")
    ap.add_argument("--out", help="write the Markdown report here (analysis.json goes next to it)")
    args = ap.parse_args()

    sample = json.load(open(args.sample))
    notes = []
    labels = load_labels(args.labels, sample["sample_sha"], args.include_post_reveal, notes)
    if not labels:
        sys.exit("no complete label rows found")
    first = None
    for p in args.labels:
        for r in csv.DictReader(open(p, newline="")):
            first = (r.get("labeler_id") or Path(p).stem).strip()
            break
        if first in labels:
            break
    args.primary = args.primary or first
    if args.primary not in labels:
        sys.exit(f"primary labeler {args.primary!r} not found; have {sorted(labels)}")
    L = labels[args.primary]
    others = [(k, v) for k, v in sorted(labels.items()) if k != args.primary]
    items = sample["items"]

    rep = [f"# Grader validation report\n",
           f"Sample `{sample['sample_sha']}` ({len(items)} items). Primary labeler: **{args.primary}**. "
           f"Bootstrap {args.boot} resamples, seed {args.seed}.\n"]
    rep.append("## 1. Coverage\n")
    rep.append("| labeler | complete items |")
    rep.append("|---|---|")
    for k, v in sorted(labels.items()):
        rep.append(f"| {k} | {len(v)} / {len(items)} |")
    rep.append("")
    sc = Counter(it["stratum"] for it in items)
    lc = Counter(it["stratum"] for it in items if it["item_id"] in L)
    rep.append("| stratum | sampled | labeled (primary) |")
    rep.append("|---|---|---|")
    for s in sorted(sc):
        rep.append(f"| {s} | {sc[s]} | {lc[s]} |")
    rep.append("")
    if notes:
        rep.append("Notes:\n")
        rep.extend(f"- {n}" for n in sorted(set(notes)))
        rep.append("")

    res = {"sample_sha": sample["sample_sha"], "primary": args.primary,
           "labeled": {k: len(v) for k, v in labels.items()}}
    section_agreement(items, L, others, args, rep, res)
    section_pr(items, L, args, rep, res)
    section_tables(sample, L, args, rep, res)
    section_precision(sample, L, rep, res)

    text = "\n".join(rep) + "\n"
    print(text)
    if args.out:
        Path(args.out).write_text(text)
        json.dump(res, open(Path(args.out).with_suffix(".json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
