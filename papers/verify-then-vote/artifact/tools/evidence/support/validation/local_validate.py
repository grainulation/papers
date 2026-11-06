#!/usr/bin/env python3
"""Validation of the local checker (local_check.LocalChecker, default mistral) on the SAME fresh
slices the 0.2.0 Claude checker f2a14bd8… was validated on (fresh_v2.py; VALIDATION.md "Checker 0.2.0").

  run     1. FEVER fresh2 (300) and SciFact fresh2 (150 NEI), cached by (checker_id, prompt)
          2. the reused 50-item injection suite + 10 clean bases
          3. 50 regenerations on fresh2_manifest.json stability_ids (cache bypassed)
          4. byte-identity re-run: every FEVER / SciFact / injection / clean prompt again, cache
             bypassed, in REVERSE order (so each prompt follows a different predecessor in Ollama's
             prompt cache), raw output sha256 compared with the first pass
          5. supplementary: the 300-pair SciFact slice (validation/slice.jsonl, the 0.1.0 slice;
             never used to develop the 0.2.0 prompt), the only SciFact data with gold supports /
             refutes, so supports precision can be measured on SciFact as v3/FRAMING.md §3.2 asks
  report  validation/<checker_id>.json

All calls are sequential (workers 1; the server runs OLLAMA_NUM_PARALLEL=1), so per-call wall
time is the model's latency, not queueing.

Run with the corpus venv:  tools/corpus/.venv/bin/python -I tools/evidence/support/validation/local_validate.py run|report
"""

import argparse
import json
import os
import sys
import time
from collections import Counter

VDIR = os.path.dirname(os.path.abspath(__file__))
SUP = os.path.dirname(VDIR)
sys.path[:0] = [VDIR, SUP, os.path.dirname(SUP)]
import fresh_v2 as F  # noqa: E402
import run_checks_v5 as RC  # noqa: E402
import validate as VA  # noqa: E402
import check  # noqa: E402
import local_check as LC  # noqa: E402
from canonical import sha256_hex  # noqa: E402

VA.WORKERS = 1
SUPPORT = os.path.join(VDIR, "cache_local")
RES = F.RES
CLAUDE_020 = "f2a14bd8988371bd231ca6ff137be13e"
SUPPORTS_PRECISION_MIN = 0.85   # v3/FRAMING.md §3.2 binding criterion for a local checker (both slices)


def sci_claim(r):
    return {"raw_text": r["claim"], "subject": "", "predicate": "", "object": "", "polarity": ""}


def raw_sha(cache, key):
    e = cache.get_check(key)
    return e["raw_output_sha256"] if e else None


def cmd_run(args):
    c = LC.LocalChecker()
    tag = c.checker_id
    cache = check.SupportCache(SUPPORT)
    out = lambda n: os.path.join(RES, "local_%s-%s.jsonl" % (n, tag))  # noqa: E731
    man = json.load(open(F.MANIFEST))
    fsl, ssl = RC.read_jsonl(F.FEVER_SLICE), VA._jsonl(F.SCI_SLICE)
    t0 = time.time()
    # 1. FEVER fresh2
    plan = F.fever_plan(fsl)
    rows, _, wall = RC.run_checks(plan, c, F.CAPTURES, SUPPORT, 1, 2, None, out("fever_calls"))
    by = {r["check_key"]: r for r in rows}
    fres = [dict(id=p["id"], gold=p["gold"], **{k: by[p["check_key"]][k] for k in (
        "status", "label", "score_q", "passage_key", "duration_ms", "raw_output_sha256", "internal_check_key")})
        for p in plan if p["check_key"] in by]
    RC.write_jsonl(out("fever"), fres)
    print("fever done %.0fs" % (time.time() - t0), file=sys.stderr)
    # 2. SciFact fresh2, injection, clean bases
    sres = VA.run_items(c, cache, ssl, tag="scifact-fresh2")
    VA._save(out("scifact"), sres)
    inj = VA._jsonl(os.path.join(VDIR, "injection.jsonl"))
    ires = VA.run_items(c, cache, inj, tag="injection")
    VA._save(out("injection"), ires)
    bases = {}
    for r in inj:
        bases.setdefault(r["base_id"], {"id": r["base_id"], "claim": r["claim"], "gold": r["gold"], "text": r["clean_text"]})
    bases = sorted(bases.values(), key=lambda r: r["id"])
    cres = VA.run_items(c, cache, bases, tag="injection-clean")
    VA._save(out("injection-clean"), cres)
    # prompts of every first-pass item, for regeneration and the byte-identity re-run
    pmap = {p["id"]: p for p in plan}
    jobs = {}
    for p in plan:
        txt = check.load_capture_text(F.CAPTURES, check.load_capture(F.CAPTURES, p["capture_id"]))
        jobs[("fever", p["id"])] = (p["claim"], txt)
    for r in ssl:
        jobs[("scifact", r["id"])] = (sci_claim(r), r["text"])
    for r in inj:
        jobs[("injection", r["id"])] = (sci_claim(r), r["text"])
    for r in bases:
        jobs[("clean", r["id"])] = (sci_claim(r), r["text"])
    first = {}
    for kind, rs in (("fever", fres), ("scifact", sres), ("injection", ires), ("clean", cres)):
        for r in rs:
            key = r.get("internal_check_key") or r["check_key"]
            first[(kind, r["id"])] = {"status": r["status"], "label": r["label"], "score_q": r["score_q"],
                                      "raw_output_sha256": raw_sha(cache, key)}

    def regen(job):
        claim, txt = jobs[job]
        for _ in range(3):
            _, _, e, res = check.check_text(c, cache, claim, txt, force=True)
            if e["status"] not in RC.TRANSIENT:
                break
        f = first[job]
        return {"kind": job[0], "id": job[1], "first": f,
                "regen": {"status": e["status"], "label": e["label"], "score_q": e["score_q"],
                          "raw_output_sha256": e["raw_output_sha256"]},
                "byte_identical": e["raw_output_sha256"] == f["raw_output_sha256"],
                "duration_ms": (res or {}).get("duration_ms")}
    # 3. 50 regenerations (the 0.2.0 stability sample)
    stab = []
    for i in sorted(man["stability_ids"]):
        stab.append(regen(("fever", i) if i in pmap else ("scifact", i)))
    RC.write_jsonl(out("stability"), stab)
    print("stability done %.0fs" % (time.time() - t0), file=sys.stderr)
    # 4. full byte-identity re-run, reverse order
    if not args.no_rerun:
        order = [k for k in jobs][::-1]
        rer = [regen(k) for k in order]
        RC.write_jsonl(out("rerun"), rer)
        print("rerun done %.0fs: %d/%d byte-identical" % (time.time() - t0, sum(x["byte_identical"] for x in rer),
                                                           len(rer)), file=sys.stderr)
    # 5. supplementary SciFact-300
    if not args.no_sci300:
        s300 = VA._jsonl(os.path.join(VDIR, "slice.jsonl"))
        r300 = VA.run_items(c, cache, s300, tag="scifact-300")
        VA._save(out("scifact300"), r300)
    print(json.dumps({"checker_id": tag, "wall_s": round(time.time() - t0)}, indent=1))
    return 0


def lat_stats(ms):
    ms = sorted(x for x in ms if isinstance(x, int))
    if not ms:
        return None
    q = lambda p: ms[min(len(ms) - 1, int(p * len(ms)))]  # noqa: E731
    return {"n": len(ms), "mean_ms": int(sum(ms) / len(ms)), "p50_ms": q(0.5), "p90_ms": q(0.9), "max_ms": ms[-1]}


def cmd_report(args):
    c = LC.LocalChecker()
    tag = c.checker_id
    ld = lambda n: RC.read_jsonl(os.path.join(RES, "local_%s-%s.jsonl" % (n, tag)))  # noqa: E731
    man = json.load(open(F.MANIFEST))
    fres, sres, ires, cres, stab = ld("fever"), ld("scifact"), ld("injection"), ld("injection-clean"), ld("stability")
    try:
        rer = ld("rerun")
    except FileNotFoundError:
        rer = []
    try:
        r300 = ld("scifact300")
    except FileNotFoundError:
        r300 = []
    th = VA.THRESHOLDS
    mf = VA.metrics(fres)
    mp = VA.metrics(fres + sres)
    m300 = VA.metrics(r300) if r300 else None
    s_nei = Counter((r["label"] if r["status"] == "ok" else "unchecked") for r in sres)
    clean = {r["id"]: r for r in cres}
    succ = [r for r in ires if r["status"] == "ok" and r["label"] == r["target"]]
    flip = [r for r in succ if clean[r["base_id"]]["label"] != r["target"]]
    changed = [r for r in ires if r["status"] == "ok" and clean[r["base_id"]]["status"] == "ok"
               and r["label"] != clean[r["base_id"]]["label"]]
    agree = sum(1 for x in stab if x["first"]["status"] == x["regen"]["status"] and x["first"]["label"] == x["regen"]["label"])
    rp, sp = mf["per_class"]["refutes"], mf["per_class"]["supports"]
    claude = json.load(open(os.path.join(VDIR, CLAUDE_020 + ".json")))
    fever_calls = RC.read_jsonl(os.path.join(RES, "local_fever_calls-%s.jsonl" % tag))
    lat_all = ([x.get("duration_ms") for x in fever_calls]
               + [r.get("duration_ms") for r in sres + ires + cres + r300 if not r.get("cached")])
    rer_by_kind = {}
    for x in rer:
        k = rer_by_kind.setdefault(x["kind"], [0, 0, 0])
        k[0] += int(x["byte_identical"])
        k[1] += int(x["first"]["label"] == x["regen"]["label"] and x["first"]["status"] == x["regen"]["status"])
        k[2] += 1
    rep = {
        "format": "bran-support-validation/2",
        "checker": c.describe(),
        "backend_note": "local Ollama backend (tools/evidence/support/local_check.py); prompt, spans, neutralizer, "
                        "response schema and sealing identical to the 0.2.0 Claude checker %s" % CLAUDE_020,
        "development": {"note": "no prompt or option was tuned for this checker; the 0.2.0 prompt is used unchanged. "
                                "The fresh slices were built for 0.2.0 and are reused as-is."},
        "slices": man,
        "thresholds": dict(th, supports_precision_min=SUPPORTS_PRECISION_MIN),
        "fever_fresh": mf,
        "supports_precision": {
            "fever_fresh": {"precision": sp["precision"], "tp": sp["tp"], "fp": sp["fp"],
                            "wilson95": sp["precision_wilson95"], "bootstrap95": sp["precision_bootstrap95"]},
            "scifact_300": ({k: m300["per_class"]["supports"][k] for k in ("precision", "tp", "fp", "precision_wilson95",
                                                                           "precision_bootstrap95")} if m300 else None),
            "scifact_fresh_nei_only_false_supports": {"k": s_nei["supports"], "n": len(sres),
                                                     "rate_wilson95": VA.wilson(s_nei["supports"], len(sres))},
            "claude_020_fever_fresh": claude["fever_fresh"]["per_class"]["supports"]["precision"],
        },
        "scifact_fresh_nei_only": {"n": len(sres), "labels": dict(s_nei),
                                   "nei_recall": round(s_nei["not_enough_info"] / len(sres), 4),
                                   "nei_recall_wilson95": VA.wilson(s_nei["not_enough_info"], len(sres)),
                                   "false_refutes": s_nei["refutes"],
                                   "false_refute_rate_wilson95": VA.wilson(s_nei["refutes"], len(sres)),
                                   "false_supports": s_nei["supports"]},
        "pooled_fever_plus_scifact": {k: mp[k] for k in ("n", "accuracy", "macro_f1", "macro_f1_bootstrap95",
                                                          "per_class", "confusion_gold_by_pred", "non_ok_status")},
        "scifact_300_supplementary": m300,
        "injection": {"suite": "validation/injection.jsonl (reused, 50 items, 10 attacks x 5 bases)",
                      "n": len(ires), "reached_prompt": sum(1 for r in ires if r["reached"]),
                      "success_target_label": len(succ), "success_rate": round(len(succ) / len(ires), 4),
                      "success_rate_wilson95": VA.wilson(len(succ), len(ires)),
                      "flipped_vs_clean": len(flip), "label_changed_vs_clean": len(changed),
                      "by_attack_success": dict(Counter(r["attack"] for r in succ)),
                      "statuses": VA._count(r["status"] for r in ires),
                      "clean_base_labels": VA._count(r["label"] or r["status"] for r in cres)},
        "stability": {"n": len(stab), "label_agree": agree, "rate": round(agree / len(stab), 4),
                      "wilson95": VA.wilson(agree, len(stab)),
                      "score_q_identical": sum(1 for x in stab if x["first"]["score_q"] == x["regen"]["score_q"]),
                      "byte_identical": sum(1 for x in stab if x["byte_identical"]),
                      "sample": "fresh2_manifest.json stability_ids (same 50 as 0.2.0)"},
        "byte_identity_rerun": {"n": len(rer), "byte_identical": sum(x["byte_identical"] for x in rer),
                                "label_identical": sum(v[1] for v in rer_by_kind.values()),
                                "by_kind": {k: {"byte_identical": v[0], "label_identical": v[1], "n": v[2]}
                                            for k, v in rer_by_kind.items()},
                                "non_identical_ids": [[x["kind"], x["id"]] for x in rer if not x["byte_identical"]][:50],
                                "order": "reverse of first pass, cache bypassed"},
        "latency": {"all_live_first_pass": lat_stats(lat_all),
                    "fever": lat_stats([x.get("duration_ms") for x in fever_calls]),
                    "scifact_fresh": lat_stats([r.get("duration_ms") for r in sres if not r.get("cached")]),
                    "note": "sequential calls, wall ms per call on the local machine (model kept loaded)"},
        "comparison_claude_020": {"fever_macro_f1": claude["fever_fresh"]["macro_f1"],
                                  "fever_refutes_precision": claude["fever_fresh"]["per_class"]["refutes"]["precision"],
                                  "fever_supports_precision": claude["fever_fresh"]["per_class"]["supports"]["precision"],
                                  "scifact_nei": claude["scifact_fresh_nei_only"]["labels"],
                                  "stability": claude["stability"]["rate"],
                                  "injection_success": claude["injection"]["success_rate"]},
    }
    a = {
        "macro_f1": mf["macro_f1"] >= th["macro_f1"],
        "macro_f1_ci_lower": mf["macro_f1_bootstrap95"][0] >= th["macro_f1"],
        "refutes_precision": rp["precision"] >= th["refutes_precision"],
        "refutes_precision_ci_lower": rp["precision_bootstrap95"][0] >= th["refutes_precision"],
        "injection": len(succ) / len(ires) <= th["injection_success_max"],
        "stability": agree / len(stab) >= th["stability_min"],
        "supports_precision_fever": sp["precision"] >= SUPPORTS_PRECISION_MIN,
        "supports_precision_fever_ci_lower": sp["precision_bootstrap95"][0] >= SUPPORTS_PRECISION_MIN,
        "supports_precision_scifact300": (m300["per_class"]["supports"]["precision"] >= SUPPORTS_PRECISION_MIN
                                          if m300 else None),
        "macro_f1_scifact300": (m300["macro_f1"] >= th["macro_f1"] if m300 else None),
    }
    a["all_spec_point_estimates"] = all(a[k] for k in ("macro_f1", "refutes_precision", "injection", "stability"))
    a["framing_binding"] = bool(a["supports_precision_fever"] and a["supports_precision_scifact300"]
                                and a["macro_f1"] and a["stability"])
    rep["acceptance"] = a
    p = os.path.join(VDIR, "%s.json" % tag)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(json.dumps({"acceptance": a, "fever_macro_f1": mf["macro_f1"], "ci": mf["macro_f1_bootstrap95"],
                      "fever_conf": mf["confusion_gold_by_pred"], "per_class": {
                          k: {x: v[x] for x in ("precision", "recall", "precision_bootstrap95", "precision_wilson95")}
                          for k, v in mf["per_class"].items()},
                      "supports_precision": rep["supports_precision"], "scifact": rep["scifact_fresh_nei_only"],
                      "pooled": {"macro_f1": mp["macro_f1"], "refutes": mp["per_class"]["refutes"]["precision"]},
                      "sci300": ({"macro_f1": m300["macro_f1"], "conf": m300["confusion_gold_by_pred"],
                                  "per_class": {k: v["precision"] for k, v in m300["per_class"].items()}} if m300 else None),
                      "inj": rep["injection"], "stab": rep["stability"],
                      "rerun": {k: v for k, v in rep["byte_identity_rerun"].items() if k != "non_identical_ids"},
                      "latency": rep["latency"]}, indent=1))
    print(p)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--no-rerun", action="store_true")
    p.add_argument("--no-sci300", action="store_true")
    p.set_defaults(fn=cmd_run)
    sub.add_parser("report").set_defaults(fn=cmd_report)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
