#!/usr/bin/env python3
"""SYNTHETIC eval-v5 records for testing evaluate_v5.py end to end (no models, no network).

Writes, under <out>/:
  items.jsonl           v5 items (v4 schema + source.subj for PopQA)
  raw/<id>.json         harness-shaped raw records (retrieval + structured answers), and raw/SYNTHETIC
  captures.jsonl        capture-shaped corpus captures (tools/evidence/corpus_capture.build_record)
  checks.jsonl          checker-shaped de-duplicated (proposition, passage) checks
  judge.jsonl           judge-shaped J / RS outputs (run 0) and a J regeneration (run 1)
  checker_id            the synthetic checker id to accept
  checks_local.jsonl    the same pairs labelled by a synthetic local checker (local_checker_id)
  judge_local.jsonl     local-judge rows (local_judge.py shape, method J) incl. a drift run
  scenarios.json        id -> scenario name and the expected outcome per method/config

Hand-written scenarios cover: a wrong majority overturned by one supported minority; a right
majority overturned by a checker false positive; the value:pooled failure (three NEI citations
outweigh one supports); a binary REFUTED answer whose passage the checker says *refutes* the claim
(label swap); PopQA aliases; parse failures; ineligible items; ties; closed-book and impossible
citations (invalid_identifier); a short passage (ok_no_text); refused and transient checks.
Seeded random filler items follow (`--filler N`).

Usage:  python3 synth_v5.py --out <dir> [--filler 220] [--seed 7] [--identifier-kind corpus]
"""
import argparse
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "tools" / "evidence"))
sys.path.insert(0, str(ROOT / "tools" / "evidence" / "support"))
import corpus_capture as CC  # noqa: E402
import propositions as PR  # noqa: E402
from canonical import canonical_bytes, sha256_hex, sha256_hex16  # noqa: E402

AGENTS = ["llama3.2_3b", "mistral", "gemma2_2b", "phi3_mini", "qwen2.5_3b"]
CORPUS = {"scifact": "scifact"}
DEFAULT_CORPUS = "fever17"
LICENSE = {"fever17": "CC BY-SA 3.0", "scifact": "ODC-By 1.0"}
CORPUS_SHA = {"fever17": "f" * 64, "scifact": "5" * 64}
FILL = ("Background sentence about an unrelated topic with enough words to pass the length gate. " * 4)


def checker_block():
    ident = {"model": "synthetic-checker", "model_digest": "hosted:none", "prompt_template_sha256": "0" * 64,
             "decoding": {k: -1 for k in ("temperature_x1000", "top_k", "top_p_x1000", "num_ctx", "num_predict", "seed")},
             "checker_tool_version": "synthetic/1"}
    cid = sha256_hex16(canonical_bytes(ident))
    return dict(ident, checker_id=cid, ollama_version="synthetic")


CHECKER = checker_block()


def corpus_of(src):
    return CORPUS.get(src, DEFAULT_CORPUS)


class World:
    def __init__(self, kind):
        self.kind = kind
        self.items, self.raw, self.captures, self.checks, self.judge, self.scen = [], {}, {}, {}, [], {}

    def capture(self, corpus_id, key, text):
        if key in self.captures:
            return self.captures[key][0]
        version = CC.tool_version(CC.make_config(), CORPUS_SHA[corpus_id])
        rec, _, _ = CC.build_record(corpus_id, key, text, LICENSE[corpus_id], version)
        rec["identifier_kind"] = self.kind
        cid = sha256_hex16(canonical_bytes(rec))
        self.captures[key] = (cid, rec)
        return cid

    def check(self, item, value, pk, value_label, status="ok", score_q=9000):
        """value_label: the label *for this value*; stored as the raw label on the proposition
        (for binary REFUTED the inverse swap; the swap is an involution)."""
        prop = PR.render(item, value)
        raw_label = PR.map_label(value_label, prop["label_map"])
        ck = PR.check_key(prop["proposition_key"], pk)
        if ck in self.checks:
            if status == "ok" and self.checks[ck]["status"] == "ok":
                assert self.checks[ck]["label"] == raw_label, ("inconsistent synthetic labels", ck)
            return
        cid = self.captures[pk][0]
        ok = status == "ok"
        self.checks[ck] = {"check_key": ck, "proposition_key": prop["proposition_key"], "proposition_text": prop["text"],
                           "passage_key": pk, "capture_id": cid, "status": status,
                           "label": raw_label if ok else None, "score_q": score_q if ok else None,
                           "raw_output_sha256": sha256_hex(f"{ck}|{raw_label}|{status}".encode()),
                           "spans": [{"start": 0, "end": 40, "text": "synthetic span"}], "checker": CHECKER,
                           "cost_usd": 0.001, "duration_ms": 3000, "input_tokens": 600, "output_tokens": 20}

    def add(self, item, passages, answers, expect=None, scenario=None, judge=None, rs=None, closed=(),
            n_results=None, check_status=None, extra_checks=()):
        """passages: [(pk, text, {value: raw label on that value's proposition})];
        answers: per agent (value, confidence, [P-labels]) or a parse-failure token."""
        self.items.append(item)
        src = item["source"]["key"]
        corp = corpus_of(src)
        for pk, text, _ in passages:
            self.capture(corp, pk, text)
        responses = []
        for i, (agent, ans) in enumerate(zip(AGENTS, answers)):
            k = len(passages) if n_results is None else n_results
            rot = passages[i % len(passages):] + passages[:i % len(passages)] if ans and ans != "skip" else passages
            shown = [] if agent in closed else rot[:min(5, k)]
            retr = None if agent in closed else {
                "format": "bran-retrieval/1", "query": f"q {item['id']} {agent}", "corpus_id": corp,
                "index_sha256": "synthetic", "k": 5,
                "results": [{"passage_key": pk, "score_q": 9000 - 10 * j} for j, (pk, _, _) in enumerate(shown)]}
            # harness shape (collect_v5.py, bran-v5-raw/1)
            r = {"agent": agent, "model": agent.replace("_", ":"), "arrival_seq": i, "arrival_rank": i,
                 "mode": "closed_book" if agent in closed else "grounded",
                 "query_turn": None if agent in closed else {"query_used": f"q {item['id']}", "query_source": "json"},
                 "retrieval": None if agent in closed else {
                     "retriever": "bm25", "record": retr, "record_verified": True,
                     "retrieval_sha256": "synthetic",
                     "passages": [{"label": f"P{j + 1}", "passage_key": x["passage_key"]}
                                  for j, x in enumerate(retr["results"])]},
                 "answer_turn": {"raw_response": "", "error": None, "ollama_meta": {"done_reason": "stop"}},
                 "parsed": {"status": "synthetic"}}
            at = r["answer_turn"]
            if ans == "error":
                at["error"] = "timeout"
            elif ans == "harness":
                r = {"agent": agent, "model": r["model"], "arrival_seq": i, "arrival_rank": i,
                     "harness_error": "RuntimeError('synthetic')", "parsed": {"status": "harness_error"}}
            elif ans == "notjson":
                at["raw_response"] = "ANSWER: A"
            elif ans == "truncated":
                at["raw_response"] = '{"reasoning": "long'
                at["ollama_meta"]["done_reason"] = "length"
            elif ans == "noanswer":
                at["raw_response"] = json.dumps({"reasoning": "x", "citations": [], "confidence": "high"})
            elif ans == "badvalue":
                at["raw_response"] = json.dumps({"reasoning": "", "answer": "Q", "citations": [], "confidence": "high"})
            elif ans is None or ans == "skip":
                continue
            else:
                value, conf, plabels = ans
                # plabels name passages by key; convert to this agent's own P-labels
                labs = []
                for p in plabels:
                    if p.startswith("P"):
                        labs.append(p)      # literal label (may be impossible)
                    else:
                        idx = [pk for pk, _, _ in shown].index(p)
                        labs.append(f"P{idx + 1}")
                at["raw_response"] = json.dumps({"reasoning": "synthetic", "answer": value, "citations": labs,
                                                 "confidence": conf})
                for lab in labs:
                    pkk = CC.citation_keys(retr or {"results": []}, [lab])[0]
                    if pkk not in self.captures:
                        self.capture(corp, pkk, None)       # invalid_identifier
                    cap = self.captures[pkk][1]
                    if cap["outcome"] != "ok":
                        continue
                    lab_raw = dict(next(p for p in passages if p[0] == pkk)[2]).get(value, "not_enough_info")
                    st = (check_status or {}).get((value, pkk), "ok")
                    self.check(item, value, pkk, lab_raw, status=st)
            responses.append(r)
        # gold-value checks on shown passages (evidence-availability diagnostic)
        gold = item["gold"]["answer"]
        for pk, _, labels in passages:
            if self.captures[pk][1]["outcome"] == "ok":
                self.check(item, gold, pk, labels.get(gold, "not_enough_info"))
        for value, pk, lab in extra_checks:
            self.check(item, value, pk, lab)
        self.raw[item["id"]] = {"id": item["id"], "responses": responses}
        self.scen[item["id"]] = {"scenario": scenario or "filler", "expect": expect or {}}
        if judge is not None:
            self.judge.append({"id": item["id"], "method": "J", "run": 0, "status": "ok" if judge else "error",
                               "selected": judge or None, "input_tokens": 4000, "output_tokens": 60, "usd": 0.008,
                               "wall_ms": 6000})
        if rs is not None:
            self.judge.append({"id": item["id"], "method": "RS", "run": 0, "status": "ok", "selected": rs,
                               "input_tokens": 3500, "output_tokens": 40, "usd": 0.006, "wall_ms": 5000})

    def write(self, out):
        out = Path(out)
        (out / "raw").mkdir(parents=True, exist_ok=True)
        (out / "raw" / "SYNTHETIC").write_text("synthetic records generated by tests/synth_v5.py\n")
        with open(out / "items.jsonl", "w") as f:
            for it in self.items:
                f.write(json.dumps(it) + "\n")
        for iid, r in self.raw.items():
            with open(out / "raw" / f"{iid}.json", "w") as f:
                json.dump(r, f, indent=1)
        with open(out / "captures.jsonl", "w") as f:
            for pk, (cid, rec) in sorted(self.captures.items()):
                f.write(json.dumps({"passage_key": pk, "capture_id": cid, "record": rec}) + "\n")
        with open(out / "checks.jsonl", "w") as f:
            for ck in sorted(self.checks):
                f.write(json.dumps(self.checks[ck]) + "\n")
        with open(out / "judge.jsonl", "w") as f:
            for j in self.judge:
                f.write(json.dumps(j) + "\n")
        (out / "checker_id").write_text(CHECKER["checker_id"])
        with open(out / "scenarios.json", "w") as f:
            json.dump(self.scen, f, indent=1, sort_keys=True)


# ── items ──

def tqa(iid, gold, n_opt=4, order=0):
    letters = "ABCDEFG"[:n_opt]
    return {"id": iid, "order": order, "source": {"key": "truthfulqa"}, "answer_format": "letter",
            "item_type": "multiple_choice", "question": f"Synthetic question {iid}?",
            "options": [{"letter": L, "text": f"Option {L} of {iid}", "correct": L == gold} for L in letters],
            "gold": {"answer": gold, "aliases": [gold]}}


def binary(iid, src, gold, order=0):
    it = {"id": iid, "order": order, "source": {"key": src}, "answer_format": "supported_refuted",
          "item_type": "binary_claim", "question": f"Synthetic claim {iid} holds.",
          "gold": {"answer": gold, "aliases": [gold]}}
    if src == "scifact":
        it["claim"] = it["question"]
    return it


def popqa(iid, gold, aliases, order=0):
    return {"id": iid, "order": order, "source": {"key": "popqa", "prop": "place of birth", "subj": f"Person {iid}",
                                                  "stratum": "pop_1e3_1e4"},
            "answer_format": "entity", "item_type": "entity", "question": f"In what city was Person {iid} born?",
            "gold": {"answer": gold, "aliases": aliases}}


def text(pk):
    return f"Passage {pk}. " + FILL


def pk(src, iid, j):
    corp = corpus_of(src)
    return f"{corp}:{iid}:{j}"


SUP, REF, NEI = "supports", "refutes", "not_enough_info"


def scenarios(w):
    o = 0
    # S1: wrong majority (A x3, NEI citations) overturned by two agents citing one supporting passage
    it = tqa("v5-s01-tqa-overturn-wrong", "B", order=o)
    P = [(pk("truthfulqa", it["id"], j), text(pk("truthfulqa", it["id"], j)), {}) for j in range(5)]
    P[0] = (P[0][0], P[0][1], {"B": SUP, "A": REF})
    w.add(it, P, [("A", "high", [P[1][0]]), ("A", "high", [P[2][0]]), ("A", "medium", []),
                  ("B", "medium", [P[0][0]]), ("B", "high", [P[0][0]])],
          scenario="wrong majority overturned (b)", expect={"MAJ": 0, "BE:all": 1, "VV": 1},
          judge="B", rs="B")
    o += 1
    # S2: right majority (SUPPORTED x3, NEI citations) flipped by a checker false positive in member mode
    it = binary("v5-s02-fever-falsepos", "fever", "SUPPORTED", order=o)
    P = [(pk("fever", it["id"], j), text(pk("fever", it["id"], j)), {}) for j in range(5)]
    P[0] = (P[0][0], P[0][1], {"SUPPORTED": REF, "REFUTED": SUP})       # false: the claim is true
    w.add(it, P, [("SUPPORTED", "high", [P[1][0]]), ("SUPPORTED", "high", [P[2][0]]),
                  ("SUPPORTED", "high", [P[3][0]]), ("REFUTED", "high", [P[0][0]]), None],
          scenario="right majority overturned by a false 'refutes' (c in member/value:max)",
          expect={"MAJ": 1, "G:member/nei0.5": 0, "G:value:max/nei0.5": 0, "G:value:pooled/nei0.5": 1},
          judge="SUPPORTED", rs="SUPPORTED")
    o += 1
    # S3: value:pooled failure: three wrong agents with NEI citations outweigh one supports
    it = tqa("v5-s03-tqa-pooled-failure", "C", order=o)
    P = [(pk("truthfulqa", it["id"], j), text(pk("truthfulqa", it["id"], j)), {}) for j in range(5)]
    P[0] = (P[0][0], P[0][1], {"C": SUP})
    w.add(it, P, [("A", "high", [P[1][0]]), ("A", "high", [P[2][0]]), ("A", "high", [P[3][0]]),
                  ("C", "high", [P[0][0]]), None],
          scenario="pooled NEI beats one supports (value:pooled keeps the wrong majority)",
          expect={"MAJ": 0, "G:member/nei0.5": 1, "G:value:max/nei0.5": 1, "G:value:pooled/nei0.5": 0,
                  "G:value:pooled/nei0.1": 1}, judge="C", rs="C")
    o += 1
    # S4: SciFact REFUTED gold; the passage refutes the claim -> mapped `supports` for REFUTED (swap)
    it = binary("v5-s04-scifact-refuted-swap", "scifact", "REFUTED", order=o)
    P = [(pk("scifact", it["id"], j), text(pk("scifact", it["id"], j)), {}) for j in range(5)]
    P[0] = (P[0][0], P[0][1], {"REFUTED": SUP, "SUPPORTED": REF})       # raw label on C: refutes
    w.add(it, P, [("SUPPORTED", "high", []), ("SUPPORTED", "high", [P[0][0]]), ("SUPPORTED", "medium", []),
                  ("REFUTED", "low", [P[0][0]]), ("REFUTED", "medium", [])],
          scenario="binary label swap: one check serves both sides", expect={"MAJ": 0, "BE:all": 1, "VV": 1},
          judge="SUPPORTED", rs="REFUTED")
    o += 1
    # S5: PopQA aliases (G-AK primary: alias inside the raw answer); wrong majority Toronto
    it = popqa("v5-s05-popqa-alias", "Ontario", ["Ontario", "ON"], order=o)
    P = [(pk("popqa", it["id"], j), text(pk("popqa", it["id"], j)), {}) for j in range(5)]
    P[0] = (P[0][0], P[0][1], {"Ontario": SUP, "Ontario, Canada": SUP})
    w.add(it, P, [("Toronto", "high", [P[1][0]]), ("Toronto", "high", []), ("Toronto", "medium", [P[2][0]]),
                  ("Ontario, Canada", "medium", [P[0][0]]), ("Ontario", "low", [P[0][0]])],
          scenario="PopQA aliases and free-text values", expect={"MAJ": 0, "BE:all": 1, "ORC": 1},
          judge="Ontario", rs="ontario")
    o += 1
    # S6: all agree (eligible, not decisive)
    it = tqa("v5-s06-all-agree", "A", order=o)
    P = [(pk("truthfulqa", it["id"], j), text(pk("truthfulqa", it["id"], j)), {"A": SUP}) for j in range(3)]
    w.add(it, P, [("A", "high", [P[0][0]])] * 5, scenario="unanimous", expect={"decisive": 0, "eligible": 1},
          judge="A", rs="A")
    o += 1
    # S7: one parsed answer only (ineligible) + every parse-failure kind
    it = tqa("v5-s07-ineligible", "A", order=o)
    P = [(pk("truthfulqa", it["id"], j), text(pk("truthfulqa", it["id"], j)), {}) for j in range(3)]
    w.add(it, P, [("A", "high", []), "error", "notjson", "noanswer", "badvalue"],
          scenario="ineligible; parse failures", expect={"eligible": 0})
    o += 1
    # S8: closed-book agent citing P1 and an agent citing P5 with 4 results (invalid_identifier, dead)
    it = tqa("v5-s08-invalid-citations", "B", order=o)
    P = [(pk("truthfulqa", it["id"], j), text(pk("truthfulqa", it["id"], j)), {}) for j in range(4)]
    P[0] = (P[0][0], P[0][1], {"B": SUP})
    w.add(it, P, [("A", "high", ["P1"]), ("A", "high", ["P5"]), ("A", "high", []),
                  ("B", "high", [P[0][0]]), ("B", "low", [])],
          closed=("llama3.2_3b",), n_results=4,
          scenario="closed-book and impossible citations", expect={"MAJ": 0, "BE:all": 1}, judge="", rs="B")
    o += 1
    # S9: short passage (ok_no_text: no support record); refused and transient checks
    it = tqa("v5-s09-nontext-refused", "D", order=o)
    short = pk("truthfulqa", it["id"], "short")
    P = [(pk("truthfulqa", it["id"], j), text(pk("truthfulqa", it["id"], j)), {}) for j in range(3)]
    P.append((short, "too short", {"D": SUP}))
    P[0] = (P[0][0], P[0][1], {"D": SUP})
    w.add(it, P, [("C", "high", [P[1][0]]), ("C", "high", [P[2][0]]), ("D", "high", [P[0][0]]),
                  ("D", "high", [P[1][0]]), ("C", "low", [])],
          check_status={("D", P[0][0]): "refused", ("D", P[1][0]): "timeout"},
          scenario="ok_no_text capture; refused (parse_error) and transient (no record) checks",
          judge="C", rs="D")
    o += 1
    # S10: right majority kept although a minority cites a NEI passage
    it = binary("v5-s10-fever-kept", "fever", "REFUTED", order=o)
    P = [(pk("fever", it["id"], j), text(pk("fever", it["id"], j)), {}) for j in range(5)]
    P[0] = (P[0][0], P[0][1], {"REFUTED": SUP, "SUPPORTED": REF})
    w.add(it, P, [("REFUTED", "high", [P[0][0]]), ("REFUTED", "high", [P[0][0]]), ("REFUTED", "medium", []),
                  ("SUPPORTED", "high", [P[1][0]]), ("SUPPORTED", "low", [])],
          scenario="right majority kept", expect={"MAJ": 1, "BE:all": 1}, judge="REFUTED", rs="REFUTED")
    o += 1
    # S11: 2-2-1 tie at the top (seeded tie-break)
    it = tqa("v5-s11-tie", "B", order=o)
    P = [(pk("truthfulqa", it["id"], j), text(pk("truthfulqa", it["id"], j)), {}) for j in range(5)]
    P[0] = (P[0][0], P[0][1], {"B": SUP})
    w.add(it, P, [("A", "high", []), ("A", "high", []), ("B", "high", [P[0][0]]), ("B", "medium", []),
                  ("C", "high", [])],
          scenario="tie at the top", expect={"BE:all": 1}, judge="B", rs="B")
    o += 1
    # S12: harness error and truncation (unparsed); a confidence outside the enum (parsed, scored low)
    it = tqa("v5-s12-harness-truncated", "A", order=o)
    P = [(pk("truthfulqa", it["id"], j), text(pk("truthfulqa", it["id"], j)), {"A": SUP}) for j in range(3)]
    w.add(it, P, [("A", "sure", [P[0][0]]), "harness", "truncated", ("B", "high", []), ("A", "low", [])],
          scenario="harness error, truncation, confidence violation", expect={"eligible": 1, "decisive": 1},
          judge="A", rs="A")
    return o + 1


def filler(w, n, seed, order0, fp=0.08):
    rng = random.Random(seed)
    srcs = ["truthfulqa", "scifact", "popqa", "fever"]
    for k in range(n):
        src = srcs[k % 4]
        iid = f"v5-f{k:03d}-{src}"
        if src == "truthfulqa":
            gold = rng.choice("ABCD")
            it = tqa(iid, gold, order=order0 + k)
            wrongs = [L for L in "ABCD" if L != gold]
        elif src == "popqa":
            gold = rng.choice(["Paris", "Lyon", "Nice"])
            it = popqa(iid, gold, [gold], order=order0 + k)
            wrongs = [c for c in ["Paris", "Lyon", "Nice", "Lille"] if c != gold]
        else:
            gold = rng.choice(["SUPPORTED", "REFUTED"])
            it = binary(iid, src, gold, order=order0 + k)
            wrongs = [x for x in PR.BINARY_VALUES if x != gold]
        # a shared misconception: one wrong value the majority tends to pick
        shared = rng.choice(wrongs)
        p_right = {"truthfulqa": 0.45, "scifact": 0.4, "popqa": 0.35, "fever": 0.7}[src]
        P = []
        for j in range(6):
            key = pk(src, iid, j)
            labels = {}
            if j == 0:
                labels = {gold: SUP, shared: REF} if rng.random() < 0.8 else {}
            elif rng.random() < fp:
                labels = {shared: SUP}          # checker false positive (drives c)
            P.append((key, text(key), labels))
        # the binary claim's raw label must be consistent between sides
        if src in ("scifact", "fever"):
            P = [(a, b, ({gold: l[gold], [x for x in PR.BINARY_VALUES if x != gold][0]: PR.map_label(l[gold], PR.SWAP)}
                         if gold in l else ({shared: l[shared], gold: PR.map_label(l[shared], PR.SWAP)}
                                            if shared in l else {}))) for a, b, l in P]
        answers = []
        for i in range(5):
            r = rng.random()
            if r < 0.03:
                answers.append("notjson")
                continue
            right = rng.random() < p_right
            v = gold if right else (shared if rng.random() < 0.75 else rng.choice(wrongs))
            conf = rng.choice(["high", "high", "medium", "low"])
            shown = (P[i % 6:] + P[:i % 6])[:5]
            if right:
                cand = [p[0] for p in shown if p[2].get(v) == SUP]
                cites = cand[:1] if cand and rng.random() < 0.85 else ([shown[1][0]] if rng.random() < 0.5 else [])
            else:
                cand = [p[0] for p in shown if p[2].get(v) == SUP]
                cites = cand[:1] if cand else ([shown[2][0]] if rng.random() < 0.6 else [])
            answers.append((v, conf, cites))
        proposed = {a[0] for a in answers if isinstance(a, tuple)}
        jsel = gold if (gold in proposed and rng.random() < 0.8) else (sorted(proposed)[0] if proposed else "")
        rs = gold if rng.random() < 0.7 else rng.choice(wrongs)
        w.add(it, P, answers, judge=jsel, rs=rs)
        if k < 40:
            w.judge.append({"id": iid, "method": "J", "run": 1, "status": "ok",
                            "selected": jsel if rng.random() < 0.9 else rng.choice(wrongs),
                            "input_tokens": 4000, "output_tokens": 60, "usd": 0.008, "wall_ms": 6000})


def local_checker_block():
    ident = {"model": "mistral:latest", "model_digest": "sha256:" + "6" * 64, "prompt_template_sha256": "1" * 64,
             "decoding": {"temperature_x1000": 0, "top_k": 1, "top_p_x1000": 1000, "num_ctx": 8192, "num_predict": 256,
                          "seed": 42},
             "checker_tool_version": "synthetic-local/1"}
    return dict(ident, checker_id=sha256_hex16(canonical_bytes(ident)), ollama_version="synthetic")


LOCAL_CHECKER = local_checker_block()


def extras(w, seed):
    """Prereg-analysis inputs: item tiers (switch build), CB-S rows, a local checker's labels,
    J_local rows (local_judge.py shape: method J), J_local drift runs and J LOAO rows."""
    rng = random.Random(seed * 7919 + 1)
    for it in w.items:
        it["tier"] = "tqa_stratum" if it["source"]["key"] == "truthfulqa" else "primary"
    local = {}
    for ck, e in sorted(w.checks.items()):
        le = dict(e, checker=LOCAL_CHECKER, cost_usd=0.0, duration_ms=9000)
        h = int(ck[:8], 16)
        if e["status"] == "ok" and e["label"] == "not_enough_info" and h % 9 == 0:
            le["label"] = "supports"                 # local false supports
        elif e["status"] == "ok" and e["label"] == "supports" and h % 5 == 0:
            le["label"] = "not_enough_info"          # local misses
        local[ck] = le
    w.local_checks = local
    j0 = {j["id"]: j for j in w.judge if j["method"] == "J" and j.get("run", 0) == 0}
    w.judge_local = []
    for it in w.items:
        iid = it["id"]
        proposed = set()
        for r in w.raw[iid]["responses"]:
            try:
                a = json.loads((r.get("answer_turn") or {}).get("raw_response") or "")
            except ValueError:
                continue
            if isinstance(a, dict) and isinstance(a.get("answer"), str):
                proposed.add(a["answer"])
        proposed = sorted(proposed)
        gold = it["gold"]["answer"]
        wrong = ([o["letter"] for o in it["options"] if o["letter"] != gold] if it.get("options")
                 else [x for x in PR.BINARY_VALUES if x != gold] if it["answer_format"] == "supported_refuted" else ["Lille"])
        w.judge.append({"id": iid, "method": "CB-S", "run": 0, "status": "ok",
                        "selected": gold if rng.random() < 0.8 else rng.choice(wrong),
                        "input_tokens": 300, "output_tokens": 30, "cache_creation_input_tokens": 0,
                        "usd": 0.002, "wall_ms": 2500, "judge_id": "synthetic-cbs"})
        if iid in j0 and proposed:
            sel = j0[iid]["selected"] if (j0[iid]["selected"] and rng.random() < 0.7) else rng.choice(proposed)
            w.judge_local.append({"id": iid, "method": "J", "run": 0, "status": "ok", "selected": sel,
                                  "input_tokens": 3000, "output_tokens": 40, "usd": 0.0, "wall_ms": 20000,
                                  "model": "mistral:latest"})
            if rng.random() < 0.3:
                w.judge_local.append({"id": iid, "method": "J", "run": 1, "status": "ok",
                                      "selected": sel if rng.random() < 0.9 else rng.choice(proposed),
                                      "input_tokens": 3000, "output_tokens": 40, "usd": 0.0, "wall_ms": 21000,
                                      "model": "mistral:latest", "drift_condition": "num_thread=4"})
    for iid in sorted(j0)[:10]:
        for a in AGENTS:
            w.judge.append({"id": iid, "method": "J", "run": 0, "dropped_agent": a, "status": "ok",
                            "selected": j0[iid]["selected"] if rng.random() < 0.85 else None,
                            "input_tokens": 3500, "output_tokens": 60, "usd": 0.007, "wall_ms": 5000})


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--filler", type=int, default=220)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--identifier-kind", default="corpus")
    ap.add_argument("--false-positive", type=float, default=0.08, help="share of filler passages falsely supporting the shared wrong value")
    a = ap.parse_args(argv)
    w = World(a.identifier_kind)
    n = scenarios(w)
    filler(w, a.filler, a.seed, n, a.false_positive)
    extras(w, a.seed)
    w.write(a.out)
    with open(Path(a.out) / "checks_local.jsonl", "w") as f:
        for ck in sorted(w.local_checks):
            f.write(json.dumps(w.local_checks[ck]) + "\n")
    with open(Path(a.out) / "judge_local.jsonl", "w") as f:
        for j in w.judge_local:
            f.write(json.dumps(j) + "\n")
    (Path(a.out) / "local_checker_id").write_text(LOCAL_CHECKER["checker_id"])
    print(f"wrote {len(w.items)} items, {len(w.captures)} captures, {len(w.checks)} checks to {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
