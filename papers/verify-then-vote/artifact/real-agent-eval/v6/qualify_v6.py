#!/usr/bin/env python3
"""
Eval v6 pool qualification on the v5 dev items (PREREGISTRATION.md section 4.3; plan section 4). Local, gold-blind for
Q1-Q3, G-AK-graded for Q4-Q5 and BEST. Reads raw records and parse_audit.json only: no Ollama, no hosted call.

Per agent (all gold-blind):
  Q1  parse failure < 0.05                      (parse_audit.json per_model status counts; rate of responses that are not ok)
  Q2  answer-turn truncation (done_reason = length) < 0.05, and no answer-turn prompt with
      prompt_eval_count + 512 > 4096            (parse_audit.json answer_truncated; ollama_meta of every answer turn)
  Q3  at least one valid citation (a label that maps to a shown passage) on >= 0.25 of parsed answers
Pool (G-AK graded, through evaluate_v5.response_view):
  Q4  yield = decisive / eligible >= 0.30         (v5's dev gate divides by all items; both are reported)
  Q5  majority-wrong share m >= 0.20 over decisive items
BEST = max(sorted(agent ids), key=#correct answers on the dev items): v5's expression, so ties go to the alphabetically first
agent id; the tied agents and the list-order alternative are reported.

`--run` is required to compute and write; without it the script checks its inputs, prints the plan and exits 2.

Usage
  qualify_v6.py --raw-dir v6/results/dev/raw --out v6/results/dev/qualification_v6.json --run
  (the dry run needs parse_audit.json next to raw/: run `collect_v6.py audit --out v6/results/dev` first)
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
V6 = Path(__file__).resolve().parent
V5 = V6.parent / "v5"
ROOT = V6.parents[1]

Q1_MAX, Q2_MAX, Q3_MIN, Q4_MIN, Q5_MIN = 0.05, 0.05, 0.25, 0.30, 0.20
NUM_CTX, ANSWER_NUM_PREDICT = 4096, 512
N_DEV = 160


def _load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


E = _load("evaluate_v5", V5 / "evaluate_v5.py")
ITEMS_DEV = V5 / "benchmark" / "items_dev.jsonl"


# ── per-agent and pool criteria (pure) ──────────────────────────

def agent_verdict(n, parse_fail, truncated, overflow, parsed, citing):
    """Q1-Q3 for one agent from counts. n responses; parsed answers; citing = parsed answers with >= 1 valid citation."""
    q1 = parse_fail / n if n else 1.0
    q2 = truncated / n if n else 1.0
    q3 = citing / parsed if parsed else 0.0
    out = {"Q1": {"value": q1, "threshold": Q1_MAX, "pass": q1 < Q1_MAX, "parse_failures": parse_fail, "responses": n},
           "Q2": {"value": q2, "threshold": Q2_MAX, "pass": q2 < Q2_MAX and overflow == 0, "truncated": truncated,
                  "prompt_overflow_responses": overflow, "rule": f"prompt_eval_count + {ANSWER_NUM_PREDICT} > {NUM_CTX}"},
           "Q3": {"value": q3, "threshold": Q3_MIN, "pass": q3 >= Q3_MIN, "citing_parsed": citing, "parsed": parsed}}
    out["pass_all"] = all(out[k]["pass"] for k in ("Q1", "Q2", "Q3"))
    return out


def pool_verdict(n_items, eligible, decisive, maj_wrong):
    y = decisive / eligible if eligible else 0.0
    y_items = decisive / n_items if n_items else 0.0
    m = maj_wrong / decisive if decisive else 0.0
    return {"Q4": {"value": y, "threshold": Q4_MIN, "pass": y >= Q4_MIN, "definition": "decisive / eligible (prereg 4.3)",
                   "value_decisive_over_all_items": y_items, "pass_if_over_all_items": y_items >= Q4_MIN,
                   "eligible": eligible, "decisive": decisive, "items": n_items},
            "Q5": {"value": m, "threshold": Q5_MIN, "pass": m >= Q5_MIN, "majority_wrong": maj_wrong, "decisive": decisive}}


def best_agent(correct):
    """v5's `max(sorted(per_agent), key=correct)`; also the tie set and the list-order alternative."""
    b = max(sorted(correct), key=lambda a: correct[a])
    top = max(correct.values())
    return b, sorted(a for a in correct if correct[a] == top)


# ── from raw records ────────────────────────────────────────────

def load_raws(raw_dir):
    return {f.stem: json.loads(f.read_text()) for f in sorted(Path(raw_dir).glob("*.json"))}


def compute(raw_dir, audit, items_path=ITEMS_DEV):
    items = E.load_items(items_path)
    raws = load_raws(raw_dir)
    if set(raws) != set(items):
        raise SystemExit(f"ABORT: raw records are not the dev items ({len(raws)} vs {len(items)}; "
                         f"missing {sorted(set(items) - set(raws))[:3]}, unknown {sorted(set(raws) - set(items))[:3]})")
    lists = {tuple(r["list_order"]) for r in raws.values()}
    if len(lists) != 1:
        raise SystemExit(f"ABORT: records disagree on list_order: {lists}")
    models = list(lists.pop())
    agents = {m: m.replace(":", "_") for m in models}
    cnt = {m: {"n": 0, "fail": 0, "overflow": 0, "parsed": 0, "citing": 0, "correct": 0, "trunc_meta": 0} for m in models}
    eligible = decisive = maj_wrong = 0
    for iid in sorted(raws, key=lambda i: (items[i].get("order", 0), i)):
        raw, item = raws[iid], items[iid]
        parsed = []
        for r in raw["responses"]:
            c = cnt[r["model"]]
            c["n"] += 1
            v = E.response_view(item, r)
            meta = ((r.get("answer_turn") or {}).get("ollama_meta")) or {}
            if meta.get("done_reason") == "length":
                c["trunc_meta"] += 1
            if meta.get("prompt_eval_count") is not None and meta["prompt_eval_count"] + ANSWER_NUM_PREDICT > NUM_CTX:
                c["overflow"] += 1
            if v["parsed"] is None:
                c["fail"] += 1
                continue
            c["parsed"] += 1
            c["correct"] += int(bool(v["correct"]))
            c["citing"] += int(any(k in v["shown"] for _, k in v["cites"]))
            parsed.append(v)
        if len(parsed) >= 2:
            eligible += 1
            n_correct = sum(1 for v in parsed if v["correct"])
            if 0 < n_correct < len(parsed):
                decisive += 1
                maj, _ = E._plurality([v["parsed"] for v in parsed], "v5-majority:" + iid)
                holders = sorted((v for v in parsed if v["parsed"] == maj), key=lambda v: v["_id"])
                maj_wrong += int(not E.grade_value(item, maj, holders[0]["answer"]))
    per = {}
    for m, c in cnt.items():
        pm = audit["per_model"][m]
        trunc = pm["answer_truncated"]
        if trunc != c["trunc_meta"]:
            raise SystemExit(f"ABORT: parse_audit.json answer_truncated {trunc} != ollama_meta count {c['trunc_meta']} for {m}")
        notok = sum(v for s, v in pm["status"].items() if not s.startswith("ok"))
        if pm["n"] != c["n"]:
            raise SystemExit(f"ABORT: parse_audit.json is stale for {m} ({pm['n']} vs {c['n']} responses); re-run `collect_v6.py audit`")
        per[agents[m]] = {"model": m, **agent_verdict(c["n"], notok, trunc, c["overflow"], c["parsed"], c["citing"]),
                          "audit_parse_failure_rate_from_status": notok / c["n"], "answers_graded_correct": c["correct"],
                          "parse_failures_from_response_view": c["fail"]}
    correct = {agents[m]: c["correct"] for m, c in cnt.items()}
    best, tied = best_agent(correct)
    pool = pool_verdict(len(raws), eligible, decisive, maj_wrong)
    fail_agents = sorted(a for a, v in per.items() if not v["pass_all"])
    return {"agents": per, "pool": pool, "n_items": len(raws), "list_order": models,
            "BEST_agent": best, "BEST_correct": correct[best], "correct_per_agent": correct,
            "BEST_tied_agents": tied,
            "BEST_note": ("v5 expression max(sorted(agent ids), key=correct) picks the alphabetically first of the tied agents; "
                          "the prereg text says 'ties by list order'"),
            "BEST_by_list_order": next(agents[m] for m in models if correct[agents[m]] == max(correct.values())),
            "agents_failing_Q1_Q3": fail_agents, "pool_pass_Q4_Q5": bool(pool["Q4"]["pass"] and pool["Q5"]["pass"]),
            "all_pass": bool(not fail_agents and pool["Q4"]["pass"] and pool["Q5"]["pass"])}


# ── cli ─────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(description="eval v6 pool qualification (local, no model calls)")
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--out", required=True, help="qualification_v6.json (must be under real-agent-eval/v6/results/)")
    ap.add_argument("--audit", help="parse_audit.json (default: next to the raw dir)")
    ap.add_argument("--items", default=str(ITEMS_DEV))
    ap.add_argument("--allow-foreign-pool", action="store_true", help="skip the pool_manifest.json check (for the v5-data sanity run only)")
    ap.add_argument("--run", action="store_true", help="compute and write; without it: check the inputs, print the plan, refuse")
    a = ap.parse_args(argv)
    out, raw_dir = Path(a.out).resolve(), Path(a.raw_dir).resolve()
    if (V6 / "results") not in out.parents:
        sys.exit(f"ABORT: --out {out} is not under {V6 / 'results'}")
    audit_p = Path(a.audit) if a.audit else raw_dir.parent / "parse_audit.json"

    checks = []

    def chk(name, ok, detail):
        checks.append((name, bool(ok), detail))

    fz = E.jload(V5 / "FREEZE.json")["sha256"]
    chk("evaluate_v5.py is the frozen file", fz.get("real-agent-eval/v5/evaluate_v5.py") == E.sha256_file(E.__file__), "v5/FREEZE.json")
    chk("dev items are the frozen file", fz.get("real-agent-eval/v5/benchmark/items_dev.jsonl") == E.sha256_file(a.items)
        if a.items == str(ITEMS_DEV) else True, str(a.items))
    n_raw = len(list(raw_dir.glob("*.json"))) if raw_dir.exists() else 0
    chk("raw records", n_raw == N_DEV, f"{n_raw} in {raw_dir} (expected {N_DEV})")
    chk("parse_audit.json", audit_p.exists(), str(audit_p))
    pm = V6 / "pool_manifest.json"
    if a.allow_foreign_pool:
        chk("pool_manifest.json", True, "skipped (--allow-foreign-pool)")
    elif pm.exists() and raw_dir.exists() and n_raw:
        first = json.loads(next(iter(sorted(raw_dir.glob("*.json")))).read_text())
        want = set(json.loads(pm.read_text()).get("model_digests", {}))
        chk("pool_manifest.json covers the agents in the records", set(first["list_order"]) <= want,
            f"records {first['list_order']}; manifest {sorted(want)}")
    else:
        chk("pool_manifest.json", pm.exists(), str(pm))
    for n, ok, d in checks:
        print(f"[{'ok' if ok else 'FAIL'}] {n}: {d}")
    print(f"plan: Q1-Q3 per agent from {audit_p.name} and the answer-turn ollama_meta; Q4-Q5 and BEST via evaluate_v5.response_view "
          f"(G-AK) on {n_raw} dev records; write {out}")
    if not a.run:
        print("REFUSED: pass --run to compute." + ("" if all(ok for _, ok, _ in checks) else " (some checks fail)"))
        return 2
    if not all(ok for _, ok, _ in checks):
        sys.exit("ABORT: input checks failed")
    res = compute(raw_dir, json.loads(audit_p.read_text()), a.items)
    res.update({"format": "bran-v6-qualification/1", "raw_dir": str(raw_dir), "parse_audit_sha256": E.sha256_file(audit_p),
                "evaluate_v5_sha256": E.sha256_file(E.__file__), "items_sha256": E.sha256_file(a.items),
                "thresholds": {"Q1": Q1_MAX, "Q2": Q2_MAX, "Q3": Q3_MIN, "Q4": Q4_MIN, "Q5": Q5_MIN},
                "note": "dev data are never pooled with confirmatory data and are not used for any test; no hosted call"})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"all_pass": res["all_pass"], "agents_failing_Q1_Q3": res["agents_failing_Q1_Q3"],
                      "Q4": res["pool"]["Q4"]["value"], "Q5": res["pool"]["Q5"]["value"], "BEST_agent": res["BEST_agent"],
                      "BEST_tied_agents": res["BEST_tied_agents"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
