#!/usr/bin/env python3
"""
Draw the stratified, seeded grader-validation sample and build the labeling page.

Reads (never writes) the v3 evaluation outputs:
  ../questions.json                                gold triples
  ../results/q*.json, ../v3/results/q*.json        responses (claims via evaluate_v3.build_contribs)
  ../v3/results/rust/<ds>/<qid>/<policy>.out.json  stored reducer `--reduce` outputs (binary NOT rerun)
  ../v3/results/precision_adjudication_{v3,v1orig}.csv, ../results/precision_adjudication.csv
  ../v3/results/paired_decisions_*.csv             used only to self-check the reconstruction

Writes (labels/ only):
  sample.json   items + all contradiction sets with every method's output (for analyze.py)
  sample.csv    flat item table WITHOUT grader verdicts (blind)
  SAMPLE.md     stratum sizes and the exact command
  label.html    self-contained labeling page (built from label_template.html)

Universe = every contribution of datasets v3 and v1orig after evaluate_v2.load_contributions,
deduplicated by (question, raw sentence, extracted triple). Each deduped claim gets exactly one
PRIMARY stratum, by priority:
  1 conflict_decisive   member of a contradiction set that is decisive under either grader
                        (Table A python slots or Table B Rust-native slots)      -> census
  2 conflict_eligible   member of an eligible, non-decisive set                     -> census
  3 precision_<cat>     Rust-admitted, fails the stricter grader; cat = heuristic   -> proportional, min per stratum
  4 grader_disagree     v1 and v2 graders disagree                                  -> simple random
  5 control_agree_yes / control_agree_no  graders agree                            -> small random slice
Weights N_h / n_h are stored so analyze.py can produce population estimates.

No label is pre-filled. Label columns stay empty.
"""

import argparse
import csv
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
sys.path.insert(0, str(EVAL))
sys.path.insert(0, str(EVAL / "v3"))
import evaluate_v1 as v1  # noqa: E402
import evaluate_v2 as ev2  # noqa: E402
import evaluate_v3 as e3  # noqa: E402

DATASETS = ["v3", "v1orig"]
RUST = EVAL / "v3" / "results" / "rust"
SHEETS = {"v3": EVAL / "v3" / "results" / "precision_adjudication_v3.csv",
          "v1orig": EVAL / "v3" / "results" / "precision_adjudication_v1orig.csv"}
OLD_SHEET = EVAL / "results" / "precision_adjudication.csv"     # v1 responses, Python reducer (evaluate_v2.py)
CATS = ["extra-but-true", "extraction-garbage", "grader-miss", "incorrect"]
GRADERS = {"v1": v1.claim_matches_gt, "v2": ev2.match_v2}


def norm(s):
    return " ".join((s or "").split()).lower()


def triple_str(c):
    return f"({c['subject']} | {c['predicate']} | {c['object']})"


def dedup_key(qid, c):
    return (qid, norm(c.get("raw_sentence", "")), norm(c["subject"]), norm(c["predicate"]), norm(c["object"]))


def v2_reason(c, gt):
    stages = [ev2.match_v2_detail(c, g)[1] for g in gt]
    return max(stages, key=ev2._STAGES.index)


# ── Conflict sets with every method's output (mirrors evaluate_v3.analyse) ──

def method_outputs_A(r, cs):
    """Table A (Python-harness slots, Rust forced policy). Returns {method: [contribution ids]}."""
    mem = cs["members"]
    ids = [m["_id"] for m in mem]
    by_id, outs = r["by_id"], r["outs"]
    o = {}
    for meth, var in [("rust", "forced"), ("rust_rec0", "forced_rec0"),
                      ("rust_nodb", "forced_nodb"), ("rust_rec0nodb", "forced_rec0nodb")]:
        kind, adm, sel = e3.rust_outcome(ids, outs[var])
        o[meth] = list(adm)
        if meth == "rust":
            o["_rust_outcome"] = kind
    kind, adm, sel = e3.rust_outcome(ids, outs["forced_evonly"])
    o["rust_evonly"] = [e3.evonly_pick(sel, by_id)] if kind == "select" else list(adm)
    o["python_bran"] = [ids[ev2.bran_idx(mem)]]
    o["python_bran_listorder"] = [ids[e3.listorder_bran(mem)]]
    o["python_no_recency"] = [ids[ev2.bran_idx(mem, {"recency": 0.0})]]
    o["evidence_only_py"] = [ids[ev2.evidence_only_idx(mem)]]
    o["majority"] = [ids[ev2.majority_idx(mem)]]
    o["first_member"] = [ids[0]]
    o["last_member"] = [ids[-1]]
    return ids, o


def method_outputs_B(r, s):
    by_id, outs = r["by_id"], r["outs"]
    ids = list(s["members"])
    mem = [by_id[i] for i in ids]
    fk = frozenset(ids)
    idx = {v: {frozenset(x["members"]): x for x in e3.rust_index(outs[v])[0]}
           for v in ["native_rec0", "native_nodb", "native_rec0nodb", "native_evonly"]}
    o = {"rust": [s["winner"]],
         "rust_rec0": [idx["native_rec0"][fk]["winner"]],
         "rust_nodb": [idx["native_nodb"][fk]["winner"]],
         "rust_rec0nodb": [idx["native_rec0nodb"][fk]["winner"]],
         "rust_evonly": [e3.evonly_pick(idx["native_evonly"][fk], by_id)],
         "python_bran_on_slot": [ids[ev2.bran_idx(mem)]],
         "majority": [ids[ev2.majority_idx(mem)]],
         "first_member": [ids[0]], "last_member": [ids[-1]]}
    return ids, o


def load_runs(ds):
    runs = []
    for q, resps, tag in e3.load_dataset(ds):
        contribs = e3.build_contribs(q, resps)
        d = RUST / ds / (q["id"] + tag)
        outs = {v: json.load(open(d / f"{v}.out.json"))
                for v in [f"{b}{m}" for b in ("native", "forced")
                          for m in ("", "_rec0", "_evonly", "_nodb", "_rec0nodb")]}
        runs.append({"q": q, "gt": [tuple(x) for x in q["ground_truth"]], "contribs": contribs,
                     "by_id": {c["_id"]: c for c in contribs}, "outs": outs,
                     "cs": v1.detect_conflicts(contribs)})
    return runs


def selfcheck(conflicts, contrib_flags):
    """Recompute paired_decisions_*.csv from the reconstructed outputs; must match exactly."""
    bad = 0
    for ds in DATASETS:
        for table, tname in [("A", "A_python_slots"), ("B", "B_rust_native_slots")]:
            for g in GRADERS:
                path = EVAL / "v3" / "results" / f"paired_decisions_{ds}_{tname}_{g}.csv"
                want = list(csv.DictReader(open(path)))
                got = []
                for cf in conflicts:
                    if cf["dataset"] != ds or cf["table"] != table:
                        continue
                    fl = [contrib_flags[(ds, i)][g] for i in cf["member_cids"]]
                    if not any(fl):
                        continue
                    row = {"question": cf["question_id"], "decisive": str(int(not all(fl)))}
                    for m, outs in cf["outputs_cids"].items():
                        row[m] = str(int(bool(outs) and all(contrib_flags[(ds, i)][g] for i in outs)))
                    got.append(row)
                if len(got) != len(want):
                    print(f"SELF-CHECK row count mismatch {path.name}: {len(got)} vs {len(want)}")
                    bad += 1
                    continue
                for a, b in zip(got, want):
                    for k, v in a.items():
                        if b.get(k) != v:
                            print(f"SELF-CHECK mismatch {path.name} {a['question']} {k}: {v} vs {b.get(k)}")
                            bad += 1
    return bad


def allocate(sizes, total, minimum):
    N = sum(sizes.values())
    out = {}
    for h, n in sizes.items():
        out[h] = min(n, max(minimum, round(total * n / N))) if N else 0
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20261021)
    ap.add_argument("--precision-total", type=int, default=40)
    ap.add_argument("--precision-min", type=int, default=6)
    ap.add_argument("--disagree", type=int, default=30)
    ap.add_argument("--control-each", type=int, default=8)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    qs = {q["id"]: q for q in json.load(open(EVAL / "questions.json"))}
    items = {}          # dedup key -> item
    cid2key = {}        # (ds, contribution id) -> dedup key
    contrib_flags = {}  # (ds, cid) -> {v1: bool, v2: bool}
    conflicts = []

    sheet_rows = {ds: {r["contribution_id"]: r for r in csv.DictReader(open(p))} for ds, p in SHEETS.items()}

    admitted_total = Counter()
    for ds in DATASETS:
        for r in load_runs(ds):
            qid, gt = r["q"]["id"], r["gt"]
            admitted_total[ds] += len(r["outs"]["native"]["admitted"])
            for c in r["contribs"]:
                k = dedup_key(qid, c)
                fl = {g: bool(ev2.correct_any(c, gt, f)) for g, f in GRADERS.items()}
                contrib_flags[(ds, c["_id"])] = fl
                cid2key[(ds, c["_id"])] = k
                it = items.get(k)
                if it is None:
                    it = items[k] = {
                        "question_id": qid, "question": r["q"]["question"], "category": r["q"]["category"],
                        "gold": [list(g) for g in gt],
                        "claim_text": c.get("raw_sentence", ""),
                        "triple": {"subject": c["subject"], "predicate": c["predicate"], "object": c["object"]},
                        "occurrences": [], "flags": set(),
                        "grader": {"v1_match": fl["v1"], "v2_match": fl["v2"], "v2_reason": v2_reason(c, gt),
                                   "heuristic_category": ev2.adjudication_category(c, gt),
                                   "in_precision_sheet": [], "sheet_rows": {}}}
                assert it["grader"]["v1_match"] == fl["v1"] and it["grader"]["v2_match"] == fl["v2"]
                it["occurrences"].append({"dataset": ds, "contribution_id": c["_id"],
                                          "agent": c["agent"], "seq": c["_seq"]})
                if c["_id"] in sheet_rows[ds]:
                    sr = sheet_rows[ds][c["_id"]]
                    assert sr["auto_category_heuristic"] == it["grader"]["heuristic_category"]
                    if ds not in it["grader"]["in_precision_sheet"]:
                        it["grader"]["in_precision_sheet"].append(ds)
                    it["grader"]["sheet_rows"][ds] = it["grader"]["sheet_rows"].get(ds, 0) + 1
                    it["flags"].add(f"precision_{sr['auto_category_heuristic']}")
                if fl["v1"] != fl["v2"]:
                    it["flags"].add("grader_disagree")
            # contradiction sets, both tables
            for cs in r["cs"]:
                if cs["type"] != "contradiction":
                    continue
                ids, o = method_outputs_A(r, cs)
                conflicts.append({"dataset": ds, "table": "A", "question_id": qid,
                                  "slot": f"({cs['key'][0]}, {cs['key'][1]})", "member_cids": ids,
                                  "rust_outcome": o.pop("_rust_outcome"), "outputs_cids": o})
            for s in e3.rust_index(r["outs"]["native"])[0]:
                ids, o = method_outputs_B(r, s)
                conflicts.append({"dataset": ds, "table": "B", "question_id": qid, "slot": s["slot"],
                                  "member_cids": ids, "rust_outcome": "select", "outputs_cids": o})

    # old Python-reducer sheet (v1 responses): join on question + claim text + triple string
    old_unmatched = 0
    by_text = defaultdict(list)
    for k, it in items.items():
        by_text[(it["question_id"], norm(it["claim_text"]), norm(triple_str(it["triple"])))].append(it)
    for r in csv.DictReader(open(OLD_SHEET)):
        hits = by_text.get((r["question"], norm(r["claim_text"]), norm(r["triple"])), [])
        if not hits:
            old_unmatched += 1
        for it in hits[:1]:
            if "v2python" not in it["grader"]["in_precision_sheet"]:
                it["grader"]["in_precision_sheet"].append("v2python")
            it["grader"]["sheet_rows"]["v2python"] = it["grader"]["sheet_rows"].get("v2python", 0) + 1

    bad = selfcheck(conflicts, contrib_flags)
    if bad:
        sys.exit(f"self-check failed ({bad} mismatches): stored Rust outputs do not reproduce paired_decisions")

    # conflict strata
    for cf in conflicts:
        for g in GRADERS:
            fl = [contrib_flags[(cf["dataset"], i)][g] for i in cf["member_cids"]]
            if any(fl):
                tag = "conflict_decisive" if not all(fl) else "conflict_eligible"
                for i in cf["member_cids"]:
                    items[cid2key[(cf["dataset"], i)]]["flags"].add(tag)

    # primary stratum by priority
    def primary(it):
        f = it["flags"]
        if "conflict_decisive" in f:
            return "conflict_decisive"
        if "conflict_eligible" in f:
            return "conflict_eligible"
        pc = [c for c in CATS if f"precision_{c}" in f]
        if pc:
            return f"precision_{pc[0]}"
        if "grader_disagree" in f:
            return "grader_disagree"
        return "control_agree_yes" if it["grader"]["v1_match"] else "control_agree_no"

    pops = defaultdict(list)
    for k in sorted(items):
        it = items[k]
        it["stratum"] = primary(it)
        pops[it["stratum"]].append(k)

    quota = {"conflict_decisive": len(pops["conflict_decisive"]),
             "conflict_eligible": len(pops["conflict_eligible"])}
    quota.update(allocate({f"precision_{c}": len(pops[f"precision_{c}"]) for c in CATS},
                          args.precision_total, args.precision_min))
    quota["grader_disagree"] = min(args.disagree, len(pops["grader_disagree"]))
    for h in ["control_agree_yes", "control_agree_no"]:
        quota[h] = min(args.control_each, len(pops[h]))

    chosen = []
    strata_report = []
    for h in quota:
        pop = pops[h]
        pick = pop if quota[h] >= len(pop) else rng.sample(pop, quota[h])
        w = len(pop) / len(pick) if pick else 0.0
        for k in pick:
            items[k]["weight"] = w
            chosen.append(k)
        strata_report.append({"stratum": h, "population": len(pop), "sampled": len(pick), "weight": round(w, 4)})

    rng.shuffle(chosen)   # blind display order: strata interleaved
    out_items = []
    for n, k in enumerate(chosen, 1):
        it = items[k]
        iid = "c" + hashlib.sha256("|".join(k).encode()).hexdigest()[:10]
        it["item_id"] = iid
        out_items.append({
            "item_id": iid, "order": n,
            "datasets": sorted({o["dataset"] for o in it["occurrences"]}),
            "question_id": it["question_id"], "question": it["question"], "category": it["category"],
            "gold": it["gold"], "claim_text": it["claim_text"], "triple": it["triple"],
            "agents": sorted({o["agent"] for o in it["occurrences"]}),
            "occurrences": it["occurrences"],
            "stratum": it["stratum"], "strata_all": sorted(it["flags"]), "weight": it["weight"],
            "grader": it["grader"]})

    # map conflicts to item ids (None = not in sample); keep every set for coverage accounting
    def iid_of(ds, cid):
        return items[cid2key[(ds, cid)]].get("item_id")
    conf_out = []
    for cf in conflicts:
        ds = cf["dataset"]
        conf_out.append({**{k: cf[k] for k in ("dataset", "table", "question_id", "slot", "rust_outcome")},
                         "members": [iid_of(ds, i) for i in cf["member_cids"]],
                         "member_cids": cf["member_cids"],
                         "grader_flags": {g: [contrib_flags[(ds, i)][g] for i in cf["member_cids"]] for g in GRADERS},
                         "outputs": {m: [iid_of(ds, i) for i in v] for m, v in cf["outputs_cids"].items()}})

    universe = {"contributions": {ds: sum(1 for x in contrib_flags if x[0] == ds) for ds in DATASETS},
                "deduped_claims": len(items)}
    blob = json.dumps(out_items, sort_keys=True, ensure_ascii=False)
    sha = hashlib.sha256(blob.encode()).hexdigest()[:16]
    sheet_totals = {}
    for name, path in list(SHEETS.items()) + [("v2python", OLD_SHEET)]:
        rows = list(csv.DictReader(open(path)))
        sheet_totals[name] = {"rows": len(rows),
                              "by_heuristic": dict(Counter(r["auto_category_heuristic"] for r in rows))}
    sample = {"sample_sha": sha, "sheet_totals": sheet_totals, "admitted_total": dict(admitted_total), "seed": args.seed, "args": vars(args), "universe": universe,
              "strata": strata_report, "old_sheet_rows_unmatched": old_unmatched,
              "items": out_items, "conflicts": conf_out}
    json.dump(sample, open(HERE / "sample.json", "w"), indent=1, ensure_ascii=False)

    # blind flat CSV
    with open(HERE / "sample.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["item_id", "order", "datasets", "question_id", "question", "gold_triples", "claim_text",
                    "subject", "predicate", "object", "agents", "correct", "matches_gold",
                    "well_formed_extraction", "notes"])
        for it in out_items:
            w.writerow([it["item_id"], it["order"], " ".join(it["datasets"]), it["question_id"], it["question"],
                        " ; ".join(f"({a} | {b} | {c})" for a, b, c in it["gold"]), it["claim_text"],
                        it["triple"]["subject"], it["triple"]["predicate"], it["triple"]["object"],
                        " ".join(it["agents"]), "", "", "", ""])

    # labeling page: items without grader block / strata; verdicts in a separate hidden block
    blind = [{k: it[k] for k in ("item_id", "order", "datasets", "question_id", "question", "gold",
                                  "claim_text", "triple", "agents")} for it in out_items]
    reveal = {it["item_id"]: {**it["grader"], "stratum": it["stratum"], "strata_all": it["strata_all"]}
              for it in out_items}
    tpl = (HERE / "label_template.html").read_text()

    def js(o):
        return json.dumps(o, ensure_ascii=False).replace("</", "<\\/")
    page = (tpl.replace("/*__SAMPLE__*/null", js({"sample_sha": sha, "items": blind}))
               .replace("/*__REVEAL__*/null", js(reveal)))
    (HERE / "label.html").write_text(page)

    # SAMPLE.md
    dec_sets = Counter()
    for cf in conf_out:
        for g in GRADERS:
            fl = cf["grader_flags"][g]
            if any(fl) and not all(fl):
                dec_sets[(cf["dataset"], cf["table"], g)] += 1
    lines = ["# Grader-validation sample", "",
             "Generated by `sample.py`. Do not edit by hand. Regenerate with:", "",
             "```sh", "cd real-agent-eval/labels",
             f"python3 sample.py --seed {args.seed} --precision-total {args.precision_total} "
             f"--precision-min {args.precision_min} --disagree {args.disagree} --control-each {args.control_each}",
             "```", "",
             f"- sample sha: `{sha}` (recorded in every exported label CSV)",
             f"- universe: {universe['contributions']['v3']} v3 + {universe['contributions']['v1orig']} v1orig "
             f"contributions, {universe['deduped_claims']} distinct claims after deduplication by "
             "(question, raw sentence, extracted triple)",
             f"- sampled items: **{len(out_items)}**",
             "- self-check: every `paired_decisions_*.csv` row (both datasets, both tables, both graders) "
             "was reproduced from the stored Rust outputs before sampling",
             "", "## Strata (primary stratum, assigned by priority top to bottom)", "",
             "| stratum | population | sampled | weight N/n |", "|---|---|---|---|"]
    for s in strata_report:
        lines.append(f"| {s['stratum']} | {s['population']} | {s['sampled']} | {s['weight']} |")
    lines += ["", "## Secondary memberships among sampled items", "",
              "An item can carry several flags; only the first by priority is its stratum.", "",
              "| flag | sampled items carrying it |", "|---|---|"]
    fc = Counter(f for it in out_items for f in it["strata_all"])
    for f_, n in sorted(fc.items()):
        lines.append(f"| {f_} | {n} |")
    by_ds = Counter(d for it in out_items for d in it["datasets"])
    lines += ["", f"Items by dataset (an item seen in both counts twice): {dict(by_ds)}.", "",
              "## Contradiction sets covered", "",
              "Decisive sets per (dataset, table, grader); all their members are in the sample:", "",
              "| dataset | table | grader | decisive sets |", "|---|---|---|---|"]
    for (d, t, g), n in sorted(dec_sets.items()):
        lines.append(f"| {d} | {t} | {g} | {n} |")
    lines += ["", f"Total contradiction sets stored for coverage accounting: {len(conf_out)} "
              f"(sets whose members no grader matched are NOT fully labeled; analyze.py reports this).",
              "", f"Old Python-reducer sheet `results/precision_adjudication.csv`: rows not found in the "
              f"universe by (question, claim text, triple): {old_unmatched}.",
              "", "## Notes", "",
              "- Strata 3-5 are drawn with `random.Random(seed)` from populations sorted by a stable key.",
              "- Display order is a seeded shuffle so strata are interleaved; the labeling page never shows the "
              "stratum or any grader verdict until the reveal step.",
              "- Precision strata use the heuristic category from the v3 adjudication sheets only to stratify. "
              "It is not a label.", ""]
    (HERE / "SAMPLE.md").write_text("\n".join(lines))
    print(f"{len(out_items)} items, sha {sha}")
    for s in strata_report:
        print(s)


if __name__ == "__main__":
    main()
