#!/usr/bin/env python3
"""Eval v5 support-check driver (v3/SWARM3_DESIGN.md §2.4, §3.4, §6.2; PREREG_DECISIONS.md).

Turns L3 raw records into the two evidence inputs of real-agent-eval/v5/evaluate_v5.py:

  captures   every passage shown to any agent (cited ⊂ shown), plus any citation label that does
             not name a shown passage (captured under the label itself -> invalid_identifier),
             via tools/evidence/corpus_capture.py, into one content-addressed cache.
             -> captures.jsonl  {"passage_key", "capture_id", "record"}
  plan       the de-duplicated (proposition, passage) checks:
               cited       every (proposition of a parsed answer, passage it cited), ok captures
               gold_shown  (proposition of the gold value, every passage shown to any agent) on the
                           items in --gold-scope (default: decisive items only). This feeds the
                           §6.2 evidence-availability gate; the checker sees an ordinary
                           proposition and is never told it is the gold one.
             Propositions come from propositions.py, check keys from propositions.check_key;
             binary items share one check per passage. The plan reads gold (decisive needs the
             G-AK grade and gold_shown needs the gold value); the checker input does not.
             -> checks_plan.jsonl
  check      runs the accepted checker (support/check.py, cached by (checker_id, prompt)) on the
             plan, retrying transient failures, and writes checks.jsonl in the format of the
             evaluate_v5.py docstring. Live-call telemetry goes to check_calls.jsonl.
  gold-avail deterministic gold-on-shown-passage check, no model: FEVER gold sentence ids against
             the shown passages' sent_ids ranges, SciFact gold doc ids against the shown passage
             keys, PopQA a gold-alias string match (heuristic), TruthfulQA none (checker only).
  judge-rows tools/judge store -> the evaluate_v5.py --judge JSONL.
  fever-build / fever-run / fever-report
             FEVER validation slice for the checker (design §3.4 lane L5, §7.3, §7.5): drawn outside
             all 347 v5 FEVER ids and all v4 FEVER items, 100 supports / 100 refutes /
             100 not_enough_info, plus a 50-pair regeneration, scored with validate.metrics against
             the SciFact thresholds.

Run with the corpus venv (gold-avail and fever-* read tools/corpus/retrieve.py):
  PY="tools/corpus/.venv/bin/python -I"
  $PY tools/evidence/support/run_checks_v5.py captures --split dev
  $PY tools/evidence/support/run_checks_v5.py plan --split dev
  $PY tools/evidence/support/run_checks_v5.py check --split dev --workers 6 --max-usd 6
"""

import argparse
import concurrent.futures as cf
import importlib.util
import json
import os
import random
import re
import sys
import threading
import time
import unicodedata
from collections import Counter, defaultdict

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
EVID = os.path.dirname(HERE)
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
V5 = os.path.join(ROOT, "real-agent-eval", "v5")
V4B = os.path.join(ROOT, "real-agent-eval", "v4", "benchmark")
CORPUS_DIR = os.path.join(ROOT, "tools", "corpus")
for p in (HERE, EVID):
    if p not in sys.path:
        sys.path.insert(0, p)
import check  # noqa: E402
import capture  # noqa: E402
import corpus_capture as CC  # noqa: E402
import propositions as PR  # noqa: E402
from canonical import canonical_json, sha256_hex  # noqa: E402

FORMAT_PLAN = "bran-v5-check-plan/1"
TRANSIENT = ("timeout", "checker_error")
VALDIR = os.path.join(HERE, "validation")
FEVER_SEED = 20261022
FEVER_PER_CLASS = 100
FEVER_STABILITY_N = 50


def load_evaluate():
    """evaluate_v5 by path (v4/canon has another make_results.py; never import that)."""
    spec = importlib.util.spec_from_file_location("evaluate_v5", os.path.join(V5, "evaluate_v5.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_jsonl(p):
    with open(p, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def write_jsonl(p, rows):
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(tmp, p)


def split_paths(args):
    out = args.out or os.path.join(V5, "results", args.split)
    items = args.items or os.path.join(V5, "benchmark", "items_%s.jsonl" % ("dev" if args.split == "dev" else "confirmatory"))
    raw = args.raw_dir or os.path.join(out, "raw")
    if "v4/results/conf" in os.path.abspath(raw).replace("\\", "/"):
        raise SystemExit("refused: v4 confirmatory data are blinded")
    cache = args.cache or os.path.join(out, "evidence-cache")
    return out, items, raw, cache


def load_raws(raw_dir):
    out = {}
    for f in sorted(os.listdir(raw_dir)):
        if f.endswith(".json"):
            with open(os.path.join(raw_dir, f), encoding="utf-8") as fh:
                r = json.load(fh)
            out[r["id"]] = r
    return out


def corpus_of(raw, resp, item=None):
    rt = resp.get("retrieval") or {}
    rec = rt.get("record") or (rt if "results" in rt else {})
    cid = rec.get("corpus_id") or raw.get("corpus") or (item or {}).get("corpus")
    if not cid:
        res = rec.get("results") or []
        cid = res[0]["passage_key"].split(":", 1)[0] if res else None
    if not cid and item is not None:   # closed-book response: design §2.2 routing by source
        cid = "scifact" if item["source"]["key"] == "scifact" else "fever17"
    return cid


# ── captures ────────────────────────────────────────────────────

def wanted_keys(items, raws, EV):
    """{corpus_id: set(passage_key)}: every shown passage, plus cited keys that are not shown."""
    want = defaultdict(set)
    for iid, raw in raws.items():
        item = items[iid]
        for r in raw["responses"]:
            cid = corpus_of(raw, r, item)
            v = EV.response_view(item, r)
            for pk in v["shown"]:
                want[cid].add(pk)
            for _, pk in v.get("cites") or []:
                want[cid].add(pk)
    return want


def cmd_captures(args):
    EV = load_evaluate()
    out, items_p, raw_dir, cache_root = split_paths(args)
    items = EV.load_items(items_p)
    raws = load_raws(raw_dir)
    want = wanted_keys(items, raws, EV)
    cache = capture.Cache(cache_root)
    rows, dist = [], Counter()
    for cid in sorted(want):
        src = CC.CorpusSource.from_manifest(args.manifest, cid)
        t0 = time.time()
        res = CC.capture_passages(sorted(want[cid]), src, cache)
        for k, capid, rec in res:
            rows.append({"passage_key": k, "capture_id": capid, "record": rec})
            dist[(cid, rec["outcome"])] += 1
        print("captured %s: %d keys in %.1fs" % (cid, len(res), time.time() - t0), file=sys.stderr)
    rows.sort(key=lambda r: r["passage_key"])
    write_jsonl(os.path.join(out, "captures.jsonl"), rows)
    summary = {"captures": len(rows), "outcomes": {"%s/%s" % k: n for k, n in sorted(dist.items())},
               "cache": os.path.relpath(cache_root, ROOT)}
    print(json.dumps(summary, indent=1))
    return 0


# ── plan ────────────────────────────────────────────────────────

def item_views(item, raw, EV):
    views = [EV.response_view(item, r) for r in sorted(raw["responses"], key=lambda r: r["arrival_seq"])]
    parsed = [v for v in views if v["parsed"] is not None]
    n_corr = sum(v["correct"] for v in parsed)
    decisive = len(parsed) >= 2 and 0 < n_corr < len(parsed)
    return views, parsed, decisive


def gold_passage(item, meta, pk):
    """Deterministic: is passage pk gold evidence for this item? FEVER: its sent_ids range covers a
    gold evidence sentence; SciFact: it is from a gold evidence abstract. None for other sources."""
    src = item["source"]["key"]
    if src == "fever":
        return any(_covers(meta.get(pk), pg, sn) for pg, sn in item["gold"].get("evidence_sentences") or [])
    if src == "scifact":
        return pk.split(":")[1] in {str(d) for d in item["gold"].get("evidence_doc_ids") or []}
    return None


def build_plan(items, raws, captures, EV, gold_scope="decisive", gold_restrict=(), meta=None):
    """De-duplicated check list (sorted by check_key) and a per-item summary.

    gold_restrict: sources whose gold_shown checks are limited to the deterministically gold
    passages (gold_passage); the other shown passages are not checked for the gold value (cost).
    Their checker-based availability is then exact only on gold passages."""
    plan = {}
    summary = []

    def add(item, prop, pk, reason, obj):
        cap = captures.get(pk)
        if cap is None:
            raise SystemExit("ABORT: no capture for %s (%s); run `captures` first" % (pk, item["id"]))
        if cap["record"]["outcome"] != "ok":
            return
        k = PR.check_key(prop["proposition_key"], pk)
        e = plan.get(k)
        if e is None:
            e = plan[k] = {"format": FORMAT_PLAN, "check_key": k, "proposition_key": prop["proposition_key"],
                           "proposition_text": prop["text"], "passage_key": pk, "capture_id": cap["capture_id"],
                           "claim": {"subject": item["id"], "predicate": "answer", "object": obj,
                                     "polarity": "AFFIRM", "raw_text": prop["text"]},
                           "reasons": [], "item_ids": []}
        if reason not in e["reasons"]:
            e["reasons"].append(reason)
        if item["id"] not in e["item_ids"]:
            e["item_ids"].append(item["id"])

    for iid in sorted(raws, key=lambda i: (items[i].get("order", 0), i)):
        item, raw = items[iid], raws[iid]
        views, parsed, decisive = item_views(item, raw, EV)
        n_cited = 0
        for v in parsed:
            for _, pk in v["cites"]:
                add(item, v["prop"], pk, "cited", v["parsed"])
                n_cited += 1
        gold_n = 0
        if gold_scope == "all" or (gold_scope == "decisive" and decisive):
            g = EV.gold_value(item)
            try:
                gp = PR.render(item, g)
            except PR.PropositionError as e:
                gp = None
                print("gold proposition not renderable for %s: %s" % (iid, e), file=sys.stderr)
            if gp is not None:
                gobj = EV.canonical_of(item, g) or g
                for pk in sorted({pk for v in views for pk in v["shown"]}):
                    if item["source"]["key"] in gold_restrict and not gold_passage(item, meta or {}, pk):
                        continue
                    add(item, gp, pk, "gold_shown", gobj)
                    gold_n += 1
        summary.append({"id": iid, "source": item["source"]["key"], "decisive": int(decisive),
                        "n_parsed": len(parsed), "citations": n_cited, "gold_shown_pairs": gold_n})
    return [plan[k] for k in sorted(plan)], summary


def load_captures_map(path):
    out = {}
    for e in read_jsonl(path):
        out.setdefault(e["passage_key"], e)
    return out


def cmd_plan(args):
    EV = load_evaluate()
    out, items_p, raw_dir, _ = split_paths(args)
    items = EV.load_items(items_p)
    raws = load_raws(raw_dir)
    caps = load_captures_map(os.path.join(out, "captures.jsonl"))
    restrict = tuple(x for x in (args.gold_restrict or "").split(",") if x)
    meta = None
    if restrict:
        meta = passage_meta(sorted({x["passage_key"] for raw in raws.values() for r in raw["responses"]
                                    for x in ((r.get("retrieval") or {}).get("record") or {}).get("results") or []}))
    plan, summary = build_plan(items, raws, caps, EV, args.gold_scope, restrict, meta)
    write_jsonl(os.path.join(out, "checks_plan.jsonl"), plan)
    by_reason = Counter("+".join(sorted(p["reasons"])) for p in plan)
    by_src = Counter(items[p["item_ids"][0]]["source"]["key"] for p in plan)
    print(json.dumps({"checks": len(plan), "by_reasons": dict(by_reason), "by_source": dict(by_src),
                      "decisive_items": sum(s["decisive"] for s in summary), "gold_scope": args.gold_scope,
                      "gold_restrict": list(restrict)},
                     indent=1))
    return 0


# ── check ───────────────────────────────────────────────────────

class CallLog:
    """Append-only live-call telemetry, keyed by check.py's internal cache key (not sealed)."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.first = {}
        if os.path.exists(path):
            for e in read_jsonl(path):
                self.first.setdefault(e["internal_key"], e)

    def add(self, e):
        with self.lock:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(e, sort_keys=True) + "\n")
            self.first.setdefault(e["internal_key"], e)


def run_one(checker, scache, cache_root, row, calllog, retries, budget):
    rec = check.load_capture(cache_root, row["capture_id"])
    text = check.load_capture_text(cache_root, rec)
    if len(text) > check.MAX_SPANS * check.BM25_PARAMS["chunk_chars"]:
        # spans would depend on the claim's subject/object, not only its text; never the case for
        # L1 passages (<= 1,000 chars + title), so refuse rather than guess
        raise SystemExit("ABORT: passage %s longer than the span budget" % row["passage_key"])
    attempt = 0
    while True:
        if budget.exhausted():
            return None
        spans, ikey, entry, res = check.check_text(checker, scache, row["claim"], text)
        if res is not None:
            calllog.add({"internal_key": ikey, "check_key": row["check_key"], "status": res["status"],
                         "cost_usd": res.get("cost_usd"), "duration_ms": res.get("duration_ms"),
                         "attempt": attempt, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            budget.spend(res.get("cost_usd") or 0.0)
        if entry["status"] not in TRANSIENT or attempt >= retries:
            break
        attempt += 1
        time.sleep(2 * attempt)
    tel = calllog.first.get(ikey) or {}
    return {"check_key": row["check_key"], "proposition_key": row["proposition_key"],
            "proposition_text": row["proposition_text"], "passage_key": row["passage_key"],
            "capture_id": row["capture_id"], "status": entry["status"], "label": entry["label"],
            "score_q": entry["score_q"], "raw_output_sha256": entry["raw_output_sha256"], "spans": spans,
            "span_selector": {"method": "bm25/1", "version": check.SPAN_SELECTOR_VERSION,
                              "params": dict(check.BM25_PARAMS)},
            "checker": checker.checker_block(), "internal_check_key": ikey,
            "model_reported": entry.get("model_reported"), "reasons": row["reasons"],
            "cost_usd": tel.get("cost_usd"), "duration_ms": tel.get("duration_ms")}


class Budget:
    def __init__(self, max_usd):
        self.max_usd, self.spent, self.lock = max_usd, 0.0, threading.Lock()

    def spend(self, x):
        with self.lock:
            self.spent += x

    def exhausted(self):
        return self.max_usd is not None and self.spent >= self.max_usd


def run_checks(plan, checker, cache_root, support_root, workers=6, retries=2, max_usd=None, log_path=None,
               progress=True):
    scache = check.SupportCache(support_root)
    calllog = CallLog(log_path or os.path.join(support_root, "check_calls.jsonl"))
    budget = Budget(max_usd)
    out, done, t0 = [None] * len(plan), [0], time.time()
    lock = threading.Lock()

    def one(i):
        out[i] = run_one(checker, scache, cache_root, plan[i], calllog, retries, budget)
        with lock:
            done[0] += 1
            if progress and done[0] % 100 == 0:
                print("  %d/%d checks, $%.3f live, %.0fs" % (done[0], len(plan), budget.spent, time.time() - t0),
                      file=sys.stderr)

    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        list(ex.map(one, range(len(plan))))
    return [r for r in out if r is not None], budget.spent, time.time() - t0


def cmd_check(args):
    out, _, _, cache_root = split_paths(args)
    plan = read_jsonl(os.path.join(out, "checks_plan.jsonl"))
    if args.limit:
        plan = plan[:args.limit]
    checker = check.Checker(claude_bin=args.claude_bin)
    if args.expect_checker and checker.checker_id != args.expect_checker:
        raise SystemExit("ABORT: checker_id %s != expected %s" % (checker.checker_id, args.expect_checker))
    rows, spent, wall = run_checks(plan, checker, cache_root, cache_root, args.workers, args.retries, args.max_usd,
                                   os.path.join(out, "check_calls.jsonl"))
    write_jsonl(os.path.join(out, "checks.jsonl"), rows)
    st = Counter(r["status"] for r in rows)
    lab = Counter((r["label"] or "-") for r in rows if r["status"] == "ok")
    print(json.dumps({"checker_id": checker.checker_id, "planned": len(plan), "written": len(rows),
                      "status": dict(st), "labels": dict(lab), "live_usd_this_run": round(spent, 4),
                      "wall_s": round(wall, 1)}, indent=1))
    return 0 if len(rows) == len(plan) else 2


# ── deterministic gold-on-shown availability ────────────────────

def _norm_text(s):
    s = unicodedata.normalize("NFKC", s).casefold()
    return " ".join(re.sub(r"[^\w\s]", " ", s).split())


def fever_evidence_sets():
    sets = {}
    for d in read_jsonl(os.path.join(V4B, "downloads", "fever", "paper_dev.jsonl")):
        sets[d["id"]] = [[(e[2], e[3]) for e in group if e[2] is not None] for group in d["evidence"]]
    return sets


def passage_meta(keys):
    sys.path.insert(0, CORPUS_DIR)
    import retrieve as R
    out = {}
    for k in keys:
        p = R.get_passage(k)
        if p is not None:
            out[k] = {"page_id": p.get("page_id"), "sent_ids": p.get("sent_ids"), "content": p["content"]}
    return out


def _covers(meta, page, sent):
    if meta is None or meta["page_id"] != page or not meta.get("sent_ids"):
        return False
    a, b = meta["sent_ids"]
    return a <= sent <= b


def gold_availability(items, raws, EV, meta, fever_sets):
    per_item = []
    for iid in sorted(raws, key=lambda i: (items[i].get("order", 0), i)):
        item, raw = items[iid], raws[iid]
        views, parsed, decisive = item_views(item, raw, EV)
        src = item["source"]["key"]
        shown = sorted({pk for v in views for pk in v["shown"]})
        row = {"id": iid, "source": src, "decisive": int(decisive), "n_shown": len(shown), "method": None,
               "available": None, "available_strict": None, "agents_with_gold": None}
        own = {v["agent"]: v["shown"] for v in views}
        if src == "fever":
            gs = [tuple(x) for x in item["gold"].get("evidence_sentences") or []]
            hit = lambda pks: any(_covers(meta.get(pk), pg, s) for pk in pks for pg, s in gs)  # noqa: E731
            sets = fever_sets.get(int(item["source"]["source_id"])) or []
            strict = lambda pks: any(all(any(_covers(meta.get(pk), pg, s) for pk in pks) for pg, s in st)  # noqa: E731
                                     for st in sets if st)
            row.update(method="fever_sent_ids", available=int(hit(shown)), available_strict=int(strict(shown)),
                       agents_with_gold=sum(int(hit(ks)) for ks in own.values()))
        elif src == "scifact":
            docs = {str(d) for d in item["gold"].get("evidence_doc_ids") or []}
            hit = lambda pks: any(pk.split(":")[1] in docs for pk in pks)  # noqa: E731
            row.update(method="scifact_doc_ids", available=int(hit(shown)), available_strict=int(hit(shown)),
                       agents_with_gold=sum(int(hit(ks)) for ks in own.values()))
        elif src == "popqa":
            aliases = [a for a in ([item["gold"]["answer"]] + list(item["gold"].get("aliases") or [])) if a]
            subj = _norm_text(item["source"].get("subj") or "")
            pats = [re.compile(r"(?<!\w)%s(?!\w)" % re.escape(_norm_text(a))) for a in aliases if _norm_text(a)]

            def hit(pks, need_subject=False):
                for pk in pks:
                    m = meta.get(pk)
                    if not m:
                        continue
                    t = _norm_text(m["content"])
                    if any(p.search(t) for p in pats) and (not need_subject or (subj and subj in t)):
                        return True
                return False
            row.update(method="popqa_alias_match (heuristic)", available=int(hit(shown)),
                       available_strict=int(hit(shown, True)), agents_with_gold=sum(int(hit(ks)) for ks in own.values()))
        else:
            row.update(method="none (checker only)")
        per_item.append(row)
    agg = {}
    for src in sorted({r["source"] for r in per_item}):
        for scope in ("decisive", "all"):
            sub = [r for r in per_item if r["source"] == src and (scope == "all" or r["decisive"])]
            av = [r for r in sub if r["available"] is not None]
            agg.setdefault(src, {})[scope] = {
                "n": len(sub), "method": sub[0]["method"] if sub else None,
                "available": sum(r["available"] for r in av) if av else None,
                "availability": (sum(r["available"] for r in av) / len(av)) if av else None,
                "available_strict": sum(r["available_strict"] for r in av) if av else None,
                "availability_strict": (sum(r["available_strict"] for r in av) / len(av)) if av else None}
    return {"note": "deterministic, no model: FEVER = a shown passage's sent_ids range covers a gold evidence "
                    "sentence (strict: some full FEVER evidence set covered by the shown passages); SciFact = a "
                    "shown passage is from a gold evidence abstract; PopQA = a gold alias occurs as a whole word "
                    "in a shown passage (strict: and the subject string too) -- a heuristic, not a support check; "
                    "TruthfulQA: no deterministic check.",
            "by_source": agg, "items": per_item}


def cmd_gold_avail(args):
    EV = load_evaluate()
    out, items_p, raw_dir, _ = split_paths(args)
    items = EV.load_items(items_p)
    raws = load_raws(raw_dir)
    keys = sorted({x["passage_key"] for raw in raws.values() for r in raw["responses"]
                   for x in ((r.get("retrieval") or {}).get("record") or {}).get("results") or []})
    meta = passage_meta(keys)
    res = gold_availability(items, raws, EV, meta, fever_evidence_sets())
    with open(os.path.join(out, "gold_availability_deterministic.json"), "w") as fh:
        json.dump(res, fh, indent=1, sort_keys=True)
    print(json.dumps(res["by_source"], indent=1))
    return 0


# ── judge store -> evaluate rows ────────────────────────────────

def judge_rows(store_root, run=0):
    recs = {}
    for e in read_jsonl(os.path.join(store_root, "index", "records.jsonl")):
        with open(os.path.join(store_root, "records", e["record_id"] + ".json"), encoding="utf-8") as fh:
            r = json.load(fh)
        recs[(r["method"], r["item_id"])] = r   # last sealed record per (method, item) wins
    tel = {}
    lp = os.path.join(store_root, "log", "calls.jsonl")
    for e in (read_jsonl(lp) if os.path.exists(lp) else []):
        if e.get("cached") is False and not e.get("regenerate"):
            tel.setdefault(e["cache_key"], e)
    rows = []
    for (m, iid), r in sorted(recs.items()):
        t = tel.get(r["cache_key"]) or {}
        u = t.get("usage") or {}
        rows.append({"id": iid, "method": m, "run": run, "status": r["status"],
                     "selected": r["answer"] if r["status"] in ("ok", "forced") else None,
                     "input_tokens": sum(u.get(k, 0) or 0 for k in (
                         "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
                     "output_tokens": u.get("output_tokens", 0) or 0, "usd": t.get("cost_usd") or 0.0,
                     "wall_ms": t.get("duration_ms") or 0})
    return rows


def cmd_judge_rows(args):
    rows = []
    for st in args.store:
        rows += judge_rows(st)
    if args.ids:
        keep = {l.strip() for l in open(args.ids) if l.strip()}
        rows = [r for r in rows if r["id"] in keep]
    write_jsonl(args.out_file, rows)
    print(json.dumps({"rows": len(rows), "by_method_status": dict(Counter(r["method"] + "/" + r["status"] for r in rows)),
                      "usd": round(sum(r["usd"] for r in rows), 4)}, default=str, indent=1))
    return 0


# ── FEVER validation slice ──────────────────────────────────────

def fever_exclusions():
    ex = set()
    for f in ("items_dev.jsonl", "items_confirmatory.jsonl"):
        for d in read_jsonl(os.path.join(V5, "benchmark", f)):
            if d["source"]["key"] == "fever":
                ex.add(int(d["source"]["source_id"]))
    n_v5 = len(ex)
    for f in ("items_dev.jsonl", "items_confirmatory.jsonl"):
        for d in read_jsonl(os.path.join(V4B, f)):
            if d["id"].startswith("v4-fever"):
                ex.add(int(d["id"][len("v4-fever"):]))
    return ex, n_v5


def _chunks_of_page(R, page, cache):
    if page not in cache:
        out, n = [], 0
        while True:
            p = R.get_passage("fever17:%s:%d" % (page, n))
            if p is None:
                break
            out.append(("fever17:%s:%d" % (page, n), p.get("sent_ids")))
            n += 1
        cache[page] = out
    return cache[page]


def cmd_fever_build(args):
    sys.path.insert(0, CORPUS_DIR)
    import retrieve as R
    ex, n_v5 = fever_exclusions()
    if n_v5 != 347:
        raise SystemExit("ABORT: expected 347 v5 FEVER ids, found %d" % n_v5)
    pdev = {d["id"]: d for d in read_jsonl(os.path.join(V4B, "downloads", "fever", "paper_dev.jsonl"))}
    reserve = json.load(open(os.path.join(V5, "benchmark", "reserve_order.json")))["reserve"]["fever"]
    pages = {}
    rows = {"supports": [], "refutes": [], "not_enough_info": []}
    # SUPPORTS / REFUTES: the reserve tail first (the front may serve a pre-declared quota move);
    # the first evidence set (file order) whose sentences all lie in one corpus passage
    for rid in reversed(reserve):
        sid = int(rid[len("v5-fever"):])
        if sid in ex or sid not in pdev:
            continue
        d = pdev[sid]
        gold = {"SUPPORTS": "supports", "REFUTES": "refutes"}.get(d["label"])
        if gold is None or len(rows[gold]) >= FEVER_PER_CLASS:
            continue
        chosen = None
        for group in d["evidence"]:
            sents = [(e[2], e[3]) for e in group]
            if not sents or any(p is None for p, _ in sents) or len({p for p, _ in sents}) != 1:
                continue
            page = sents[0][0]
            for key, rng in _chunks_of_page(R, page, pages):
                if rng and all(rng[0] <= s <= rng[1] for _, s in sents):
                    chosen = (key, sents)
                    break
            if chosen:
                break
        if chosen:
            rows[gold].append({"id": "fever%d" % sid, "fever_id": sid, "claim": PR.clean(d["claim"]), "gold": gold,
                               "passage_key": chosen[0], "evidence": [list(x) for x in chosen[1]],
                               "origin": "v5 reserve tail (fever)"})
        if all(len(rows[k]) >= FEVER_PER_CLASS for k in ("supports", "refutes")):
            break
    # NOT ENOUGH INFO: paper_dev NEI claims (never in any item set), seeded order; the passage is the
    # claim's BM25 top-1 in fever17 (the agents' retriever): on-topic but, per FEVER, not evidence
    nei = sorted(i for i, d in pdev.items() if d["label"] == "NOT ENOUGH INFO" and i not in ex)
    random.Random(FEVER_SEED).shuffle(nei)
    for sid in nei:
        if len(rows["not_enough_info"]) >= FEVER_PER_CLASS:
            break
        rec = R.retrieve(pdev[sid]["claim"], "fever17", k=1)
        if not rec["results"]:
            continue
        rows["not_enough_info"].append({"id": "fever%d" % sid, "fever_id": sid, "claim": PR.clean(pdev[sid]["claim"]),
                                        "gold": "not_enough_info", "passage_key": rec["results"][0]["passage_key"],
                                        "evidence": [], "origin": "paper_dev NEI, BM25 top-1"})
    sl = rows["supports"] + rows["refutes"] + rows["not_enough_info"]
    assert not ({r["fever_id"] for r in sl} & ex), "exclusion violated"
    assert len({r["fever_id"] for r in sl}) == len(sl)
    path = os.path.join(VALDIR, "fever_slice.jsonl")
    write_jsonl(path, sl)
    rng = random.Random(FEVER_SEED + 1)
    stab = sorted(rng.sample([r["id"] for r in sl], FEVER_STABILITY_N))
    proof = {"slice_sha256": sha256_hex(open(path, "rb").read()), "n": len(sl),
             "per_class": {k: len(v) for k, v in rows.items()}, "excluded_fever_ids": len(ex),
             "excluded_v5_fever_ids": n_v5, "overlap_with_excluded": 0, "stability_ids": stab,
             "seed": FEVER_SEED, "rule": "SUP/REF from reversed reserve_order.json fever list, first evidence set "
             "contained in one fever17 passage; NEI from paper_dev NEI claims shuffled by Random(seed), BM25 top-1"}
    with open(os.path.join(VALDIR, "fever_slice_manifest.json"), "w") as fh:
        json.dump(proof, fh, indent=1, sort_keys=True)
    print(json.dumps({k: proof[k] for k in ("n", "per_class", "excluded_fever_ids", "slice_sha256")}, indent=1))
    return 0


def cmd_fever_run(args):
    sl = read_jsonl(os.path.join(VALDIR, "fever_slice.jsonl"))
    man = json.load(open(os.path.join(VALDIR, "fever_slice_manifest.json")))
    croot = os.path.join(VALDIR, "fever_cache")
    cache = capture.Cache(croot)
    src = CC.CorpusSource.from_manifest(args.manifest, "fever17")
    caps = {k: (cid, rec) for k, cid, rec in CC.capture_passages(sorted({r["passage_key"] for r in sl}), src, cache)}
    plan = []
    for r in sl:
        cid, rec = caps[r["passage_key"]]
        if rec["outcome"] != "ok":
            raise SystemExit("ABORT: capture %s outcome %s" % (r["passage_key"], rec["outcome"]))
        pk = PR.proposition_key(r["claim"])
        plan.append({"check_key": PR.check_key(pk, r["passage_key"]), "proposition_key": pk,
                     "proposition_text": r["claim"], "passage_key": r["passage_key"], "capture_id": cid,
                     "claim": {"subject": r["id"], "predicate": "answer", "object": "SUPPORTED", "polarity": "AFFIRM",
                               "raw_text": r["claim"]}, "reasons": ["fever_validation"], "gold": r["gold"], "id": r["id"]})
    checker = check.Checker(claude_bin=args.claude_bin)
    rows, spent, wall = run_checks(plan, checker, croot, croot, args.workers, args.retries, args.max_usd,
                                   os.path.join(VALDIR, "results", "fever_calls.jsonl"))
    by_key = {r["check_key"]: r for r in rows}
    res = [dict(id=p["id"], gold=p["gold"], **{k: by_key[p["check_key"]][k] for k in (
        "status", "label", "score_q", "passage_key", "cost_usd", "duration_ms")}) for p in plan if p["check_key"] in by_key]
    write_jsonl(os.path.join(VALDIR, "results", "fever_slice_results.jsonl"), res)
    # regeneration: fresh calls on the stability subset (first cached answer stays authoritative)
    stab = set(man["stability_ids"])
    scache = check.SupportCache(croot)
    regen = []

    def one(p):
        rec = check.load_capture(croot, p["capture_id"])
        txt = check.load_capture_text(croot, rec)
        for _ in range(3):
            _, _, e, r = check.check_text(checker, scache, p["claim"], txt, force=True)
            if e["status"] not in TRANSIENT:
                break
        first = by_key[p["check_key"]]
        return {"id": p["id"], "first": {"status": first["status"], "label": first["label"], "score_q": first["score_q"]},
                "regen": {"status": e["status"], "label": e["label"], "score_q": e["score_q"]},
                "cost_usd": (r or {}).get("cost_usd"), "duration_ms": (r or {}).get("duration_ms")}
    if not args.no_stability:
        with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
            regen = list(ex.map(one, [p for p in plan if p["id"] in stab]))
        write_jsonl(os.path.join(VALDIR, "results", "fever_stability.jsonl"), regen)
    print(json.dumps({"checked": len(res), "status": dict(Counter(r["status"] for r in res)),
                      "live_usd": round(spent + sum(x["cost_usd"] or 0 for x in regen), 4), "wall_s": round(wall, 1),
                      "regen": len(regen)}, indent=1))
    return 0


def cmd_fever_report(args):
    import validate as VA
    res = read_jsonl(os.path.join(VALDIR, "results", "fever_slice_results.jsonl"))
    man = json.load(open(os.path.join(VALDIR, "fever_slice_manifest.json")))
    regen_p = os.path.join(VALDIR, "results", "fever_stability.jsonl")
    regen = read_jsonl(regen_p) if os.path.exists(regen_p) else []
    checker = check.Checker(claude_bin=args.claude_bin)
    m = VA.metrics(res)
    ok_only = VA.metrics([r for r in res if r["status"] == "ok"]) if any(r["status"] != "ok" for r in res) else None
    agree = sum(1 for x in regen if x["first"]["label"] == x["regen"]["label"] and x["first"]["status"] == x["regen"]["status"])
    th = VA.THRESHOLDS
    calls = read_jsonl(os.path.join(VALDIR, "results", "fever_calls.jsonl"))
    cost = sum(c.get("cost_usd") or 0 for c in calls) + sum(x.get("cost_usd") or 0 for x in regen)
    lat = sorted(c["duration_ms"] for c in calls if isinstance(c.get("duration_ms"), int))
    rep = {"format": "bran-support-validation/fever/1", "checker": checker.describe(), "slice": man,
           "thresholds": {"macro_f1": th["macro_f1"], "refutes_precision": th["refutes_precision"],
                          "stability_min": th["stability_min"]},
           "metrics": m, "metrics_ok_only": ok_only,
           "pass": {"macro_f1": m["macro_f1"] >= th["macro_f1"],
                    "macro_f1_ci_lower": m["macro_f1_bootstrap95"][0] >= th["macro_f1"],
                    "refutes_precision": m["per_class"]["refutes"]["precision"] >= th["refutes_precision"],
                    "refutes_precision_ci_lower": m["per_class"]["refutes"]["precision_bootstrap95"][0] >= th["refutes_precision"],
                    "stability": (agree / len(regen) >= th["stability_min"]) if regen else None},
           "stability": {"n": len(regen), "label_agree": agree, "rate": agree / len(regen) if regen else None,
                         "wilson95": VA.wilson(agree, len(regen)) if regen else None,
                         "score_q_identical": sum(1 for x in regen if x["first"]["score_q"] == x["regen"]["score_q"])},
           "cost": {"live_calls": len(calls) + len(regen), "usd": round(cost, 4),
                    "median_latency_ms": lat[len(lat) // 2] if lat else None},
           "injection": "not re-run (passages are fixed corpus text; the SciFact suite stands for this checker_id)"}
    p = os.path.join(VALDIR, "%s.fever.json" % checker.checker_id)
    with open(p, "w") as fh:
        json.dump(rep, fh, indent=1, sort_keys=True)
    print(json.dumps({"macro_f1": m["macro_f1"], "macro_f1_ci": m["macro_f1_bootstrap95"],
                      "refutes_precision": m["per_class"]["refutes"]["precision"],
                      "refutes_precision_ci": m["per_class"]["refutes"]["precision_bootstrap95"],
                      "supports_precision": m["per_class"]["supports"]["precision"],
                      "accuracy": m["accuracy"], "confusion": m["confusion_gold_by_pred"], "pass": rep["pass"],
                      "stability": rep["stability"], "cost": rep["cost"]}, indent=1))
    return 0


# ── CLI ─────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--claude-bin", default=check.DEFAULT_CLAUDE)
    ap.add_argument("--manifest", default=CC.DEFAULT_MANIFEST)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def split_args(p):
        p.add_argument("--split", choices=["dev", "conf"], default="dev")
        p.add_argument("--items")
        p.add_argument("--raw-dir")
        p.add_argument("--out", help="split output dir (default real-agent-eval/v5/results/<split>)")
        p.add_argument("--cache", help="evidence cache root (default <out>/evidence-cache)")
    p = sub.add_parser("captures")
    split_args(p)
    p.set_defaults(fn=cmd_captures)
    p = sub.add_parser("plan")
    split_args(p)
    p.add_argument("--gold-scope", choices=["decisive", "all", "none"], default="decisive")
    p.add_argument("--gold-restrict", default="",
                   help="comma list of sources (fever,scifact) whose gold checks cover only deterministic gold passages")
    p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("check")
    split_args(p)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--retries", type=int, default=2)
    p.add_argument("--max-usd", type=float, help="stop issuing live calls once this much was spent")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--expect-checker", default="76d44ce22b1ea2f476539e36daacc81a")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("gold-avail")
    split_args(p)
    p.set_defaults(fn=cmd_gold_avail)
    p = sub.add_parser("judge-rows")
    p.add_argument("--store", action="append", required=True)
    p.add_argument("--ids", help="keep only these item ids (one per line)")
    p.add_argument("--out-file", required=True)
    p.set_defaults(fn=cmd_judge_rows)
    p = sub.add_parser("fever-build")
    p.set_defaults(fn=cmd_fever_build)
    p = sub.add_parser("fever-run")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--retries", type=int, default=2)
    p.add_argument("--max-usd", type=float, default=2.0)
    p.add_argument("--no-stability", action="store_true")
    p.set_defaults(fn=cmd_fever_run)
    p = sub.add_parser("fever-report")
    p.set_defaults(fn=cmd_fever_report)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
