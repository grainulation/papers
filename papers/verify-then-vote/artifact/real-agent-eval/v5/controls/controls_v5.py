#!/usr/bin/env python3
"""Exploratory checker controls for v5 (see README.md in this directory).

  build    reconstruct BE-G on set P from the sealed conf inputs, collect witness pairs (W)
           and a seeded comparison sample (R), render M / S prompts, estimate cost
  run      hosted calls for M and S (pinned CLI, cache bypassed), logged to calls.jsonl
  analyze  label tables (Wilson CIs) and counterfactual BE-G decisions with substituted labels

Run: DISABLE_AUTOUPDATER=1 python3 -I real-agent-eval/v5/controls/controls_v5.py <cmd>
Never writes into the support store, checks.jsonl, or any frozen file.
"""

import argparse
import concurrent.futures as cf
import copy
import hashlib
import importlib.util
import json
import os
import random
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
V5 = HERE.parent
ROOT = V5.parent.parent
CONF = V5 / "results" / "conf"
SUPPORT = ROOT / "tools" / "evidence" / "support"
sys.path.insert(0, str(SUPPORT))
sys.path.insert(0, str(SUPPORT.parent))

CHECKER_ID = "f2a14bd8988371bd231ca6ff137be13e"
# Install CLI 2.1.307 on PATH or set BRAN_CLAUDE_BIN; checker_id verifies the pin.
CLAUDE_BIN = os.path.expanduser(os.environ.get("BRAN_CLAUDE_BIN", "claude"))
FROZEN_BIN = V5 / "frozen-bin" / "bran"
BE_G = "member/nei0.5/gated"
SEED = "v5-controls"
MASK = "[passage withheld]"
MAX_USD = 10.0
EST_PER_CALL = 0.005
POP = HERE / "population.jsonl"
CALLS = HERE / "calls.jsonl"
RUST_DIR = Path(os.environ.get("CONTROLS_RUST_DIR", str(ROOT / "bench-output" / "controls-rust")))


def load_ev():
    spec = importlib.util.spec_from_file_location("evaluate_v5", str(V5 / "evaluate_v5.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def read_jsonl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def write_jsonl(p, rows):
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")


# ── reconstruction ─────────────────────────────────────────────

class World:
    """Sealed conf inputs, prepared P records, and BE-G / MAJ decisions."""

    def __init__(self, checks=None):
        self.EV = EV = load_ev()
        self.items = EV.load_items(str(V5 / "benchmark" / "items_confirmatory.jsonl"))
        self.raws = {f.stem: EV.jload(f) for f in sorted((CONF / "raw").glob("*.json"))}
        self.captures = EV.load_captures(str(CONF / "captures.jsonl"))
        self.checks = checks if checks is not None else EV.load_checks(str(CONF / "checks.jsonl"))
        args = SimpleNamespace(strict=False, bin=str(FROZEN_BIN), accepted_checker=[CHECKER_ID])
        self.ctx = EV.Ctx(args, self.captures, self.checks, {}, accepted=[CHECKER_ID])
        self.ctx.rdir = RUST_DIR
        ids = sorted(self.raws, key=lambda i: (self.items[i].get("order", 0), i))
        self.recs = {}
        for i in ids:
            it = self.items[i]
            if EV.analysis_set(it, strict=True) != "P":
                continue
            rec = EV.prepare_item(it, self.raws[i], self.ctx)
            if rec["row"]["eligible"]:
                self.recs[i] = rec

    def maj(self, rec):
        EV = self.EV
        maj, _ = EV._plurality([v["parsed"] for v in rec["parsed"]], "v5-majority:" + rec["item"]["id"])
        return maj, EV.object_correct(rec, maj)[0]

    def decide(self, rec, tag):
        return self.EV.reduce_method(rec, "BE", BE_G, self.ctx, tag)


def witness_pairs(W, rec, res):
    """Licensing (check_key, value) pairs of a gated overturn (as evaluate_v5._witnesses)."""
    gt = (res["sel"] or {}).get("gate")
    if not gt or not gt["overturned"]:
        return []
    wobj = rec["by_id"][res["winner"]]["parsed"]
    out = {}
    for i in gt["witnesses"]:
        v = rec["by_id"][i]
        if v["parsed"] != wobj:
            continue
        for a in v["audit"]:
            if a.get("support_label") == "supports" and a.get("support_status") == "ok" and a.get("accepted"):
                out.setdefault(a["check"], {"check_key": a["check"], "passage_key": a["passage_key"],
                                            "value": wobj, "label_map": v["prop"]["label_map"]})
    return [out[k] for k in sorted(out)]


def passage_text(entry):
    return "\n[...]\n".join(sp["text"] for sp in entry["spans"])


def title_of(entry):
    return entry["spans"][0]["text"].split("\n", 1)[0].strip() if entry["spans"] else ""


def cmd_build(args):
    import check as CK
    w = World()
    EV = w.EV
    dec = 0
    b = c = 0
    rows_pd = {r["id"]: r for r in __import__("csv").DictReader(open(CONF / "eval" / "paired_decisions_v5.csv"))}
    mism = 0
    pop, overturn_items, winners = [], {}, set()
    for iid, rec in w.recs.items():
        res = w.decide(rec, "orig")
        maj, maj_ok = w.maj(rec)
        pd = rows_pd[iid]
        if int(pd["BE-G"]) != res["correct"] or int(pd["MAJ"]) != maj_ok:
            mism += 1
        gt = (res["sel"] or {}).get("gate")
        if gt and gt["overturned"]:
            winners.add((iid, res["obj"]))
        if not rec["row"]["decisive"]:
            continue
        dec += 1
        kind = "b" if res["correct"] and not maj_ok else "c" if maj_ok and not res["correct"] else None
        b += kind == "b"
        c += kind == "c"
        if kind and gt and gt["overturned"]:
            overturn_items[iid] = kind
            for p in witness_pairs(w, rec, res):
                pop.append(dict(p, group="W", kind=kind, item_id=iid, source=rec["item"]["source"]["key"]))
    print(f"P eligible={len(w.recs)} decisive={dec} b={b} c={c} mismatches_vs_paired_csv={mism} "
          f"overturn_items={len(overturn_items)} W_pairs={len(pop)}", file=sys.stderr)
    if mism or (b, c) != (91, 12):
        raise SystemExit("ABORT: reconstruction does not reproduce the reported BE-G decisions")
    wkeys = {p["check_key"] for p in pop}
    # comparison pool: (check, value) with mapped label supports, cited, P, value not an overturn winner
    pool = {}
    for iid, rec in w.recs.items():
        for v in rec["parsed"]:
            if (iid, v["parsed"]) in winners:
                continue
            for a in v["audit"]:
                if a.get("support_label") == "supports" and a.get("support_status") == "ok" and a.get("accepted") \
                        and a["check"] not in wkeys:
                    pool.setdefault(a["check"], {"check_key": a["check"], "passage_key": a["passage_key"],
                                                 "value": v["parsed"], "label_map": v["prop"]["label_map"],
                                                 "group": "R", "kind": "R", "item_id": iid,
                                                 "source": rec["item"]["source"]["key"]})
    keys = sorted(pool)
    pick = random.Random(SEED).sample(keys, min(len(pop), len(keys)))
    pop += [pool[k] for k in sorted(pick)]
    print(f"R pool={len(pool)} R sample={len(pick)}", file=sys.stderr)

    # prompts
    checker = CK.Checker(claude_bin=CLAUDE_BIN)
    if checker.checker_id != CHECKER_ID:
        raise SystemExit(f"ABORT: checker_id {checker.checker_id} != {CHECKER_ID}")
    by_src = defaultdict(dict)   # source -> passage_key -> entry (donor pool: every checked passage)
    plan_items = {e["check_key"]: e["item_ids"] for e in read_jsonl(CONF / "checks_plan.jsonl")}
    for k, e in w.checks.items():
        for iid in plan_items.get(k, []):
            src = w.items[iid]["source"]["key"]
            if src != "truthfulqa":
                by_src[src].setdefault(e["passage_key"], (e, iid))
    shown = {iid: {pk for v in rec["views"] for pk in v["shown"]} for iid, rec in w.recs.items()}
    for p in pop:
        e = w.checks[p["check_key"]]
        claim = e["proposition_text"]
        orig_passages = [sp["text"] for sp in e["spans"]]
        user0 = CK.render_user(checker.template, claim, orig_passages)
        key0 = CK.sha256_hex16(CK.canonical_bytes({"checker_id": checker.checker_id,
                                                   "prompt_sha256": CK.sha256_hex(user0.encode("utf-8"))}))
        if key0 != e["internal_check_key"]:
            raise SystemExit(f"ABORT: original prompt not reproduced for {p['check_key']}")
        item = w.items[p["item_id"]]
        p.update(proposition_text=claim, proposition_key=e["proposition_key"], orig_raw_label=e["label"],
                 orig_score_q=e["score_q"], orig_len=len(passage_text(e)))
        p["M_user"] = CK.render_user(checker.template, claim, [MASK])
        # shuffled donor
        rng = random.Random(f"{SEED}:S:{p['check_key']}")
        ttl = title_of(e).casefold()
        forbid = [claim.casefold()]
        extra = []
        if p["source"] == "popqa":
            extra = [CK.neutralize(str(item["source"].get("subj") or "")).casefold(), str(p["value"]).casefold()]
        cands = []
        for pk, (de, diid) in sorted(by_src[p["source"]].items()):
            if diid == p["item_id"] or pk in shown[p["item_id"]]:
                continue
            dt = title_of(de).casefold()
            txt = passage_text(de).casefold()
            if not dt or dt == ttl or dt in claim.casefold() or (ttl and ttl in txt):
                continue
            if any(x and x in txt for x in extra):
                continue
            cands.append((pk, de))
        near = [x for x in cands if abs(len(passage_text(x[1])) - p["orig_len"]) <= 0.3 * p["orig_len"]]
        if near:
            dpk, de = rng.choice(near)
        else:
            dpk, de = min(cands, key=lambda x: (abs(len(passage_text(x[1])) - p["orig_len"]), x[0]))
        p.update(S_donor=dpk, S_len=len(passage_text(de)), S_within30=bool(near))
        p["S_user"] = CK.render_user(checker.template, claim, [sp["text"] for sp in de["spans"]])
    m_prompts = {sha(p["M_user"]) for p in pop}
    s_prompts = {sha(p["S_user"]) for p in pop}
    n_calls = len(m_prompts) + len(s_prompts)
    est = n_calls * EST_PER_CALL
    write_jsonl(POP, pop)
    summary = {"W": len([p for p in pop if p["group"] == "W"]), "R": len([p for p in pop if p["group"] == "R"]),
               "W_by_kind": dict(Counter(p["kind"] for p in pop if p["group"] == "W")),
               "overturn_items": dict(Counter(overturn_items.values())),
               "M_distinct_prompts": len(m_prompts), "S_distinct_prompts": len(s_prompts),
               "planned_calls": n_calls, "estimated_usd": round(est, 3),
               "S_within30": sum(p["S_within30"] for p in pop)}
    print(json.dumps(summary, indent=1))
    if est > MAX_USD:
        raise SystemExit("ABORT: projected cost exceeds $10")
    return 0


# ── calls ───────────────────────────────────────────────────────

def cmd_run(args):
    import check as CK
    if os.environ.get("DISABLE_AUTOUPDATER") != "1":
        raise SystemExit("ABORT: set DISABLE_AUTOUPDATER=1")
    checker = CK.Checker(claude_bin=CLAUDE_BIN)
    if checker.checker_id != CHECKER_ID:
        raise SystemExit(f"ABORT: checker_id {checker.checker_id} != {CHECKER_ID}")
    pop = read_jsonl(POP)
    todo = {}
    for p in pop:
        for cond in ("M", "S"):
            u = p[cond + "_user"]
            todo.setdefault((cond, sha(u)), u)
    done = {}
    if CALLS.exists():
        for e in read_jsonl(CALLS):
            if e["status"] in CK.CACHEABLE:
                done[(e["condition"], e["prompt_sha256"])] = e
    pending = [(k, u) for k, u in sorted(todo.items()) if k not in done]
    spent = [sum(e.get("cost_usd") or 0 for e in read_jsonl(CALLS))] if CALLS.exists() else [0.0]
    if spent[0] + len(pending) * EST_PER_CALL > MAX_USD:
        raise SystemExit(f"ABORT: projected ${spent[0] + len(pending) * EST_PER_CALL:.2f} > ${MAX_USD}")
    print(f"pending={len(pending)} already_done={len(done)} spent_so_far=${spent[0]:.4f}", file=sys.stderr)
    lock = threading.Lock()
    sys_sha = sha(checker.template["system"])

    def one(job):
        (cond, psha), user = job
        for attempt in range(3):
            with lock:
                if spent[0] >= MAX_USD - 0.05:
                    return
            res = checker.call(user)
            row = {"condition": cond, "prompt_sha256": psha, "system_sha256": sys_sha,
                   "flags_sha256": checker.flags_sha256, "checker_id": checker.checker_id,
                   "inputs_sha256": sha(json.dumps([sys_sha, checker.flags_sha256, psha])),
                   "status": res["status"], "label": res.get("label"), "score_q": res.get("score_q"),
                   "model_reported": res.get("model_reported"), "cost_usd": res.get("cost_usd"),
                   "duration_ms": res.get("duration_ms"), "attempt": attempt,
                   "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            with lock:
                spent[0] += res.get("cost_usd") or 0.0
                with open(CALLS, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, sort_keys=True) + "\n")
            if res["status"] in CK.CACHEABLE:
                return
            time.sleep(2 * (attempt + 1))

    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for n, _ in enumerate(ex.map(one, pending), 1):
            if n % 50 == 0:
                print(f"  {n}/{len(pending)} ${spent[0]:.3f} {time.time() - t0:.0f}s", file=sys.stderr)
    print(f"done: spent_total=${spent[0]:.4f} wall={time.time() - t0:.0f}s", file=sys.stderr)
    return 0


# ── analysis ────────────────────────────────────────────────────

def cmd_analyze(args):
    import propositions as PR
    EV = load_ev()
    pop = read_jsonl(POP)
    calls = read_jsonl(CALLS)
    lab = {}
    for e in calls:
        if e["status"] in ("ok", "parse_error", "model_mismatch", "input_too_long", "refused"):
            lab.setdefault((e["condition"], e["prompt_sha256"]), e)
    cost = sum(e.get("cost_usd") or 0 for e in calls)
    out = {"calls": len(calls), "calls_by_status": dict(Counter(e["status"] for e in calls)),
           "total_cost_usd": round(cost, 4), "population": {}, "tables": {}, "counterfactual": {}}
    out["population"] = {"W": sum(p["group"] == "W" for p in pop), "R": sum(p["group"] == "R" for p in pop),
                         "W_by_kind": dict(Counter(p["kind"] for p in pop if p["group"] == "W")),
                         "W_by_source": dict(Counter(p["source"] for p in pop if p["group"] == "W")),
                         "W_items": dict(Counter(k for _, k in {(p["item_id"], p["kind"]) for p in pop if p["group"] == "W"})),
                         "S_within30": sum(p["S_within30"] for p in pop)}
    for p in pop:
        for cond in ("M", "S"):
            e = lab.get((cond, sha(p[cond + "_user"])))
            p[cond + "_raw"] = e["label"] if e and e["status"] == "ok" else None
            p[cond + "_status"] = e["status"] if e else "missing"
            p[cond + "_score_q"] = e["score_q"] if e and e["status"] == "ok" else None
            p[cond] = PR.map_label(p[cond + "_raw"], p["label_map"]) if p[cond + "_raw"] else "no_label"
        p["orig"] = PR.map_label(p["orig_raw_label"], p["label_map"])
    assert all(p["orig"] == "supports" for p in pop)

    def table(rows, cond):
        cnt = Counter(r[cond] for r in rows)
        n = len(rows)
        k = cnt.get("supports", 0)
        return {"n": n, "labels": dict(cnt), "supports_rate": k / n if n else None,
                "supports_wilson95": EV.wilson(k, n) if n else None}

    groups = {"W": [p for p in pop if p["group"] == "W"], "W_b": [p for p in pop if p["kind"] == "b"],
              "W_c": [p for p in pop if p["kind"] == "c"], "R": [p for p in pop if p["group"] == "R"]}
    for src in sorted({p["source"] for p in pop}):
        groups["W_" + src] = [p for p in pop if p["group"] == "W" and p["source"] == src]
        groups["R_" + src] = [p for p in pop if p["group"] == "R" and p["source"] == src]
    for cond in ("M", "S"):
        out["tables"][cond] = {g: table(rs, cond) for g, rs in groups.items()}

    # counterfactual: substitute control labels on W pairs, re-decide every affected P item
    wpairs = [p for p in pop if p["group"] == "W"]
    base = World()
    orig = {}
    majs = {}
    for iid, rec in base.recs.items():
        orig[iid] = base.decide(rec, "orig")["correct"]
        majs[iid] = base.maj(rec)[1]

    def summarize(dec_correct):
        rows = [{"m": dec_correct[i], "MAJ": majs[i]} for i, r in base.recs.items() if r["row"]["decisive"]]
        n = len(rows)
        ov = EV.overturn(rows, "m")
        return {"n_decisive": n, "accuracy": sum(r["m"] for r in rows) / n, "b": ov["b"], "c": ov["c"],
                "MAJ_accuracy": sum(r["MAJ"] for r in rows) / n}

    out["counterfactual"]["original"] = summarize(orig)
    for cond in ("M", "S"):
        checks = copy.deepcopy(base.checks)
        changed = set()
        for p in wpairs:
            e = checks[p["check_key"]]
            st = p[cond + "_status"]
            if st == "ok":
                e["label"], e["score_q"] = p[cond + "_raw"], p[cond + "_score_q"]
            else:
                e["status"], e["label"], e["score_q"] = (st if st in EV.SEALABLE else "parse_error"), None, None
            changed.add(p["check_key"])
        w2 = World(checks=checks)
        decs = dict(orig)
        n_redecided = 0
        for iid, rec in w2.recs.items():
            keys = {a["check"] for v in rec["parsed"] for a in v["audit"] if a.get("check")}
            if keys & changed:
                decs[iid] = w2.decide(rec, "cf_" + cond)["correct"]
                n_redecided += 1
        s = summarize(decs)
        s["items_redecided"] = n_redecided
        s["note"] = ("exploratory: substituted labels come from a different checker input "
                     "(masked/shuffled passage) than the sealed records describe; not preregistered")
        out["counterfactual"][cond] = s
    out["pairs"] = [{k: p[k] for k in ("group", "kind", "item_id", "source", "check_key", "passage_key",
                                       "orig", "M", "S", "S_donor")} for p in pop]
    with open(HERE / "results.json", "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    print(json.dumps({k: v for k, v in out.items() if k != "pairs"}, indent=1))
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    r = sub.add_parser("run")
    r.add_argument("--workers", type=int, default=6)
    r.set_defaults(fn=cmd_run)
    sub.add_parser("analyze").set_defaults(fn=cmd_analyze)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
