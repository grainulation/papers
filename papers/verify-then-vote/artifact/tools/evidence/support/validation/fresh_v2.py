#!/usr/bin/env python3
"""Fresh-slice validation of the 0.2.0 checker (prompt v2). See VALIDATION.md, "Checker 0.2.0".

The 0.2.0 prompt was iterated on the first FEVER slice (validation/fever_slice.jsonl) and the
SciFact pilot (validation/pilot.jsonl). This script draws NEW slices disjoint from both and from
every benchmark id, then runs the checker once on them.

  build   FEVER: paper_dev claims outside the v5 items (dev + confirmatory), the v5 reserve_order
          FEVER list, the v4 items, and the first FEVER slice. SUPPORTS/REFUTES: seeded shuffle,
          first evidence set contained in one fever17 passage (the first slice's rule). NEI: seeded
          shuffle, the claim's BM25 top-1 fever17 passage. 100 per class.
          SciFact: validate.candidates() outside the v4 benchmark ids (VALIDATION.md §1), the v5
          SciFact items and reserve, and the earlier slice, pilot and injection bases. Only NEI pairs
          survive that exclusion (every remaining SUPPORT/CONTRADICT claim is a v5 item or reserve),
          so the SciFact fresh slice is 150 NEI pairs.
  run     slice checks (cached), the reused 50-item injection suite + 10 clean bases, and 50
          regenerations sampled from the pooled fresh slices.
  report  validation/<checker_id>.json

Run with the corpus venv:  tools/corpus/.venv/bin/python -I tools/evidence/support/validation/fresh_v2.py build|run|report
"""

import argparse
import concurrent.futures as cf
import json
import os
import random
import sys
from collections import Counter

VDIR = os.path.dirname(os.path.abspath(__file__))
SUP = os.path.dirname(VDIR)
sys.path[:0] = [SUP, os.path.dirname(SUP)]
import run_checks_v5 as RC  # noqa: E402
import validate as VA  # noqa: E402
import check  # noqa: E402
import capture  # noqa: E402
import corpus_capture as CC  # noqa: E402
import propositions as PR  # noqa: E402
from canonical import sha256_hex  # noqa: E402

SEED = 20261023
FEVER_PER_CLASS = 100
SCIFACT_NEI_N = 150
STABILITY_N = 50
FEVER_SLICE = os.path.join(VDIR, "fever_slice_fresh2.jsonl")
SCI_SLICE = os.path.join(VDIR, "scifact_slice_fresh2.jsonl")
MANIFEST = os.path.join(VDIR, "fresh2_manifest.json")
CAPTURES = os.path.join(VDIR, "fever_cache")       # content-addressed corpus captures (shared)
SUPPORT = os.path.join(VDIR, "cache_fresh2")       # support-check cache for this run
RES = os.path.join(VDIR, "results")


def v5_ids():
    fever, sci = set(), set()
    for f in ("items_dev.jsonl", "items_confirmatory.jsonl"):
        for d in RC.read_jsonl(os.path.join(RC.V5, "benchmark", f)):
            if d["source"]["key"] == "fever":
                fever.add(int(d["source"]["source_id"]))
            elif d["source"]["key"] == "scifact":
                sci.add("v4-" + d["id"][len("v5-"):])
    res = json.load(open(os.path.join(RC.V5, "benchmark", "reserve_order.json")))["reserve"]
    fever |= {int(r[len("v5-fever"):]) for r in res["fever"]}
    sci |= {"v4-" + r[len("v5-"):] for r in res["scifact"]}
    return fever, sci


def cmd_build(args):
    sys.path.insert(0, RC.CORPUS_DIR)
    import retrieve as R
    ex_items, n_v5 = RC.fever_exclusions()
    v5f, v5s = v5_ids()
    first = {r["fever_id"] for r in RC.read_jsonl(os.path.join(VDIR, "fever_slice.jsonl"))}
    ex = ex_items | v5f | first
    pdev = {d["id"]: d for d in RC.read_jsonl(os.path.join(RC.V4B, "downloads", "fever", "paper_dev.jsonl"))}
    pool = sorted(i for i in pdev if i not in ex)
    random.Random(SEED).shuffle(pool)
    rows = {"supports": [], "refutes": [], "not_enough_info": []}
    pages = {}
    for sid in pool:
        d = pdev[sid]
        gold = {"SUPPORTS": "supports", "REFUTES": "refutes", "NOT ENOUGH INFO": "not_enough_info"}[d["label"]]
        if len(rows[gold]) >= FEVER_PER_CLASS:
            continue
        if gold == "not_enough_info":
            rec = R.retrieve(d["claim"], "fever17", k=1)
            if rec["results"]:
                rows[gold].append({"id": "fever%d" % sid, "fever_id": sid, "claim": PR.clean(d["claim"]), "gold": gold,
                                   "passage_key": rec["results"][0]["passage_key"], "evidence": [],
                                   "origin": "paper_dev NEI (fresh2), BM25 top-1"})
        else:
            chosen = None
            for group in d["evidence"]:
                sents = [(e[2], e[3]) for e in group]
                if not sents or any(p is None for p, _ in sents) or len({p for p, _ in sents}) != 1:
                    continue
                for key, rng in RC._chunks_of_page(R, sents[0][0], pages):
                    if rng and all(rng[0] <= s <= rng[1] for _, s in sents):
                        chosen = (key, sents)
                        break
                if chosen:
                    break
            if chosen:
                rows[gold].append({"id": "fever%d" % sid, "fever_id": sid, "claim": PR.clean(d["claim"]), "gold": gold,
                                   "passage_key": chosen[0], "evidence": [list(x) for x in chosen[1]],
                                   "origin": "paper_dev %s (fresh2)" % d["label"]})
        if all(len(v) >= FEVER_PER_CLASS for v in rows.values()):
            break
    fsl = rows["supports"] + rows["refutes"] + rows["not_enough_info"]
    assert all(len(v) == FEVER_PER_CLASS for v in rows.values()), {k: len(v) for k, v in rows.items()}
    assert not ({r["fever_id"] for r in fsl} & ex) and len({r["fever_id"] for r in fsl}) == len(fsl)
    RC.write_jsonl(FEVER_SLICE, fsl)

    # SciFact
    v4ex = VA.excluded_ids()
    used = set()
    for f in ("slice.jsonl", "pilot.jsonl"):
        used |= {r["id"] for r in VA._jsonl(os.path.join(VDIR, f))}
    used |= {r["base_id"] for r in VA._jsonl(os.path.join(VDIR, "injection.jsonl"))}
    sex = v4ex | v5s | used
    cands = VA.candidates()
    avail = {k: sorted((r for r in v if r["id"] not in sex), key=lambda r: r["id"]) for k, v in cands.items()}
    nei = list(avail["not_enough_info"])
    random.Random(SEED).shuffle(nei)
    ssl = sorted(({k: r[k] for k in ("id", "claim", "doc_id", "gold", "text")} for r in nei[:SCIFACT_NEI_N]),
                 key=lambda r: r["id"])
    assert len(ssl) == SCIFACT_NEI_N and not ({r["id"] for r in ssl} & sex)
    VA._write_jsonl(SCI_SLICE, ssl)

    pooled = sorted([r["id"] for r in fsl] + [r["id"] for r in ssl])
    stab = sorted(random.Random(SEED + 1).sample(pooled, STABILITY_N))
    man = {"seed": SEED,
           "fever": {"path": os.path.basename(FEVER_SLICE), "sha256": sha256_hex(open(FEVER_SLICE, "rb").read()),
                     "n": len(fsl), "per_class": {k: len(v) for k, v in rows.items()},
                     "excluded_ids": len(ex), "excluded_breakdown": {
                         "v5_items": n_v5, "v5_reserve_and_items": len(v5f), "v4_and_v5_items": len(ex_items),
                         "first_fever_slice": len(first)},
                     "pool_after_exclusion": len(pool),
                     "rule": "paper_dev outside v5 items + v5 reserve + v4 items + first FEVER slice; Random(seed) "
                             "shuffle; SUP/REF need the first evidence set inside one fever17 passage; NEI BM25 top-1"},
           "scifact": {"path": os.path.basename(SCI_SLICE), "sha256": VA.slice_hash(ssl), "n": len(ssl),
                       "per_class": dict(Counter(r["gold"] for r in ssl)),
                       "available_after_exclusion": {k: len(v) for k, v in avail.items()},
                       "excluded": {"v4_benchmark": len(v4ex), "v5_items_and_reserve": len(v5s),
                                    "earlier_slice_pilot_injection": len(used), "union": len(sex)},
                       "rule": "validate.candidates() outside v4 benchmark + v5 SciFact items/reserve + earlier "
                               "slice/pilot/injection bases; only NEI remains; Random(seed) shuffle, first %d" % SCIFACT_NEI_N},
           "stability_ids": stab}
    with open(MANIFEST, "w") as fh:
        json.dump(man, fh, indent=1, sort_keys=True)
    print(json.dumps({k: man[k] for k in ("fever", "scifact")}, indent=1))
    return 0


def _checker():
    os.makedirs(os.path.join(VDIR, ".cli-cwd"), exist_ok=True)
    return check.Checker(workdir=os.path.join(VDIR, ".cli-cwd"))


def fever_plan(fsl):
    src = CC.CorpusSource.from_manifest(CC.DEFAULT_MANIFEST, "fever17")
    caps = {k: (cid, rec) for k, cid, rec in
            CC.capture_passages(sorted({r["passage_key"] for r in fsl}), src, capture.Cache(CAPTURES))}
    plan = []
    for r in fsl:
        cid, rec = caps[r["passage_key"]]
        if rec["outcome"] != "ok":
            raise SystemExit("ABORT: capture %s outcome %s" % (r["passage_key"], rec["outcome"]))
        pk = PR.proposition_key(r["claim"])
        plan.append({"check_key": PR.check_key(pk, r["passage_key"]), "proposition_key": pk,
                     "proposition_text": r["claim"], "passage_key": r["passage_key"], "capture_id": cid,
                     "claim": {"subject": r["id"], "predicate": "answer", "object": "SUPPORTED", "polarity": "AFFIRM",
                               "raw_text": r["claim"]}, "reasons": ["fever_validation_fresh2"], "gold": r["gold"],
                     "id": r["id"]})
    return plan


def cmd_run(args):
    c = _checker()
    man = json.load(open(MANIFEST))
    fsl, ssl = RC.read_jsonl(FEVER_SLICE), VA._jsonl(SCI_SLICE)
    cache = check.SupportCache(SUPPORT)
    tag = c.checker_id
    # FEVER slice
    plan = fever_plan(fsl)
    rows, spent, _ = RC.run_checks(plan, c, CAPTURES, SUPPORT, 6, 2, args.max_usd,
                                   os.path.join(RES, "fresh2_fever_calls-%s.jsonl" % tag))
    by = {r["check_key"]: r for r in rows}
    fres = [dict(id=p["id"], gold=p["gold"], **{k: by[p["check_key"]][k] for k in (
        "status", "label", "score_q", "passage_key", "cost_usd", "duration_ms")}) for p in plan if p["check_key"] in by]
    RC.write_jsonl(os.path.join(RES, "fresh2_fever-%s.jsonl" % tag), fres)
    # SciFact slice
    sres = VA.run_items(c, cache, ssl, tag="scifact-fresh2")
    VA._save(os.path.join(RES, "fresh2_scifact-%s.jsonl" % tag), sres)
    # injection (reused suite) + clean bases
    inj = VA._jsonl(os.path.join(VDIR, "injection.jsonl"))
    ires = VA.run_items(c, cache, inj, tag="injection")
    VA._save(os.path.join(RES, "injection-%s.jsonl" % tag), ires)
    bases = {}
    for r in inj:
        bases.setdefault(r["base_id"], {"id": r["base_id"], "claim": r["claim"], "gold": r["gold"], "text": r["clean_text"]})
    cres = VA.run_items(c, cache, sorted(bases.values(), key=lambda r: r["id"]), tag="injection-clean")
    VA._save(os.path.join(RES, "injection-clean-%s.jsonl" % tag), cres)
    # regeneration on the pooled stability sample (cache bypassed; first answer stays authoritative)
    stab = set(man["stability_ids"])
    first = {r["id"]: r for r in fres + sres}
    pmap = {p["id"]: p for p in plan}
    smap = {r["id"]: r for r in ssl}

    def one(i):
        if i in pmap:
            p = pmap[i]
            txt = check.load_capture_text(CAPTURES, check.load_capture(CAPTURES, p["capture_id"]))
            claim = p["claim"]
        else:
            txt = smap[i]["text"]
            claim = {"raw_text": smap[i]["claim"], "subject": "", "predicate": "", "object": "", "polarity": ""}
        for _ in range(3):
            _, _, e, r = check.check_text(c, cache, claim, txt, force=True)
            if e["status"] not in RC.TRANSIENT:
                break
        f = first[i]
        return {"id": i, "first": {"status": f["status"], "label": f["label"], "score_q": f["score_q"]},
                "regen": {"status": e["status"], "label": e["label"], "score_q": e["score_q"]},
                "cost_usd": (r or {}).get("cost_usd"), "duration_ms": (r or {}).get("duration_ms")}
    with cf.ThreadPoolExecutor(6) as ex:
        regen = list(ex.map(one, sorted(stab)))
    RC.write_jsonl(os.path.join(RES, "fresh2_stability-%s.jsonl" % tag), regen)
    print(json.dumps({"checker_id": tag, "fever": dict(Counter(r["status"] for r in fres)),
                      "scifact": dict(Counter(r["status"] for r in sres)), "regen": len(regen)}, indent=1))
    return 0


def _live_cost(rows, key="cost_usd"):
    return sum((r.get(key) or 0) for r in rows if not r.get("cached", False))


def cmd_report(args):
    c = _checker()
    tag = c.checker_id
    man = json.load(open(MANIFEST))
    ld = lambda n: RC.read_jsonl(os.path.join(RES, "%s-%s.jsonl" % (n, tag)))
    fres, sres, ires, cres, regen = (ld("fresh2_fever"), ld("fresh2_scifact"), ld("injection"),
                                     ld("injection-clean"), ld("fresh2_stability"))
    fcalls = ld("fresh2_fever_calls")
    th = VA.THRESHOLDS
    mf = VA.metrics(fres)
    mp = VA.metrics(fres + sres)
    s_nei = Counter((r["label"] if r["status"] == "ok" else "unchecked") for r in sres)
    clean = {r["id"]: r for r in cres}
    succ = [r for r in ires if r["status"] == "ok" and r["label"] == r["target"]]
    flip = [r for r in succ if clean[r["base_id"]]["label"] != r["target"]]
    changed = [r for r in ires if r["status"] == "ok" and clean[r["base_id"]]["status"] == "ok"
               and r["label"] != clean[r["base_id"]]["label"]]
    agree = sum(1 for x in regen if x["first"]["status"] == x["regen"]["status"] and x["first"]["label"] == x["regen"]["label"])
    stab = agree / len(regen)
    refused = {"fever": sum(1 for r in fres if r["status"] == "refused"),
               "scifact": sum(1 for r in sres if r["status"] == "refused"),
               "injection": sum(1 for r in ires if r["status"] == "refused"),
               "injection_clean": sum(1 for r in cres if r["status"] == "refused"),
               "stability": sum(1 for x in regen if x["regen"]["status"] == "refused")}
    cost = {"fever_slice": round(sum(x.get("cost_usd") or 0 for x in fcalls), 4),
            "scifact_slice": round(_live_cost(sres), 4),
            "injection": round(_live_cost(ires + cres), 4),
            "stability": round(sum(x.get("cost_usd") or 0 for x in regen), 4)}
    cost["total"] = round(sum(cost.values()), 4)
    lat = sorted(x["duration_ms"] for x in fcalls if isinstance(x.get("duration_ms"), int))
    rp = mf["per_class"]["refutes"]
    rep = {
        "format": "bran-support-validation/2",
        "checker": c.describe(),
        "development": {"note": "prompt iterated on validation/fever_slice.jsonl (first FEVER slice) and "
                                "validation/pilot.jsonl (SciFact pilot); see VALIDATION.md. Not used below.",
                        "previous_checker": "76d44ce22b1ea2f476539e36daacc81a"},
        "slices": man,
        "thresholds": th,
        "fever_fresh": mf,
        "scifact_fresh_nei_only": {"n": len(sres), "labels": dict(s_nei),
                                   "nei_recall": round(s_nei["not_enough_info"] / len(sres), 4),
                                   "nei_recall_wilson95": VA.wilson(s_nei["not_enough_info"], len(sres)),
                                   "false_refutes": s_nei["refutes"],
                                   "false_refute_rate_wilson95": VA.wilson(s_nei["refutes"], len(sres)),
                                   "false_supports": s_nei["supports"]},
        "pooled_fever_plus_scifact": {k: mp[k] for k in ("n", "accuracy", "macro_f1", "macro_f1_bootstrap95",
                                                          "per_class", "confusion_gold_by_pred", "non_ok_status")},
        "injection": {"suite": "validation/injection.jsonl (reused, 50 items, 10 attacks x 5 bases)",
                      "sha256": VA.slice_hash(VA._jsonl(os.path.join(VDIR, "injection.jsonl"))),
                      "n": len(ires), "reached_prompt": sum(1 for r in ires if r["reached"]),
                      "success_target_label": len(succ), "success_rate": round(len(succ) / len(ires), 4),
                      "success_rate_wilson95": VA.wilson(len(succ), len(ires)),
                      "flipped_vs_clean": len(flip), "label_changed_vs_clean": len(changed),
                      "statuses": VA._count(r["status"] for r in ires),
                      "clean_base_labels": VA._count(r["label"] or r["status"] for r in cres)},
        "stability": {"n": len(regen), "label_agree": agree, "rate": round(stab, 4),
                      "wilson95": VA.wilson(agree, len(regen)),
                      "score_q_identical": sum(1 for x in regen if x["first"]["score_q"] == x["regen"]["score_q"]),
                      "sample": "50 ids from the pooled fresh FEVER + SciFact slices, Random(seed+1)",
                      "from_fever": sum(1 for x in regen if x["id"].startswith("fever"))},
        "refusals": refused,
        "cost": dict(cost, median_latency_ms_fever=lat[len(lat) // 2] if lat else None),
    }
    rep["acceptance"] = {
        "macro_f1": mf["macro_f1"] >= th["macro_f1"],
        "macro_f1_ci_lower": mf["macro_f1_bootstrap95"][0] >= th["macro_f1"],
        "refutes_precision": rp["precision"] >= th["refutes_precision"],
        "refutes_precision_ci_lower": rp["precision_bootstrap95"][0] >= th["refutes_precision"],
        "injection": len(succ) / len(ires) <= th["injection_success_max"],
        "stability": stab >= th["stability_min"],
        "pooled_refutes_precision": mp["per_class"]["refutes"]["precision"] >= th["refutes_precision"],
    }
    rep["acceptance"]["all_point_estimates"] = all(rep["acceptance"][k] for k in
                                                   ("macro_f1", "refutes_precision", "injection", "stability"))
    p = os.path.join(VDIR, "%s.json" % tag)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(json.dumps({"acceptance": rep["acceptance"], "fever_macro_f1": mf["macro_f1"],
                      "fever_macro_f1_ci": mf["macro_f1_bootstrap95"],
                      "fever_refutes_p": rp["precision"], "ci": rp["precision_bootstrap95"],
                      "wilson": rp["precision_wilson95"],
                      "fever_supports_p": mf["per_class"]["supports"]["precision"],
                      "fever_conf": mf["confusion_gold_by_pred"], "scifact": rep["scifact_fresh_nei_only"],
                      "pooled": {"macro_f1": mp["macro_f1"], "refutes_p": mp["per_class"]["refutes"]["precision"],
                                 "refutes_ci": mp["per_class"]["refutes"]["precision_bootstrap95"]},
                      "inj": rep["injection"], "stab": rep["stability"], "refused": refused, "cost": rep["cost"]},
                     indent=1))
    print(p)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    p = sub.add_parser("run")
    p.add_argument("--max-usd", type=float, default=3.0)
    p.set_defaults(fn=cmd_run)
    sub.add_parser("report").set_defaults(fn=cmd_report)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
