#!/usr/bin/env python3
"""
Eval v4 analysis (PREREGISTRATION.md §3-§6, §11.2). Reads results/<split>/raw/<id>.json
written by collect_v4.py.

Pipeline per item
  1. parse       answer_key.parse_answer (gold-blind) on every response; answer_key.answer_line
                 keeps the raw ANSWER line (needed by the PopQA alias grader).
  2. slot        one functional slot (v4-<id>, answer, ·) holding the parseable answers.
                 Eligible: >= 2 parseable answers. Decisive: eligible and the members contain
                 >= 1 correct and >= 1 incorrect answer under G-AK (method-blind).
  3. contribute  one contribution per parsed answer (§4.3):
                   triple       (v4-<id>, answer, <canonical object>), AFFIRM
                   evidence     every evidence item that evaluate_v2.load_contributions
                                (associate=True) attaches to the v3-extracted claims of the same
                                response (ANSWER lines removed before extraction), de-duplicated
                                by text; UNVERIFIED, reachable = true (v3 lowering)
                   confidence   v3 hedge rule (../collect.py) applied to the ANSWER line:
                                HIGH .85 / MEDIUM .65 / LOW .45; lowering_confidence HIGH
                   seq          arrival_seq * 1000;  calibration 0.7 (v3)
                   id           sha256(item|agent|answer|object)[:16] (content hash, order-free)
                 The raw source lines of the response are kept verbatim with each response
                 (`source_lines`) so evidence identifiers can be extracted later (L4b/H3).
  4. reduce      `bran --reduce` once per Rust method (M1, M3, M4, M5, M6), each a policy
                 overlay on evaluate_v3.DEFAULT_POLICY with values.incompatible_values =
                 {"answer": {"__all_objects__": <every observed object>}} (v3 "forced"
                 restricted to `answer`; gold-blind), so the slot is exclusive.
  5. python      M2, M7-M12; a Python mirror of selection must equal the binary on every slot
                 (abort on mismatch).
  6. grade       answer_key.grade (G-AK). A method that selects a member is graded on that
                 member's ANSWER line. A method that selects a canonical object (M2, M7) is
                 graded on the ANSWER line of the object's member with the smallest
                 contribution id (order-free); objects whose members grade differently are
                 counted (`objects_with_mixed_member_correctness`).
  7. statistics  exact McNemar (v3 definition, evaluate_v2.mcnemar_exact), Newcombe hybrid
                 score CI (method 10) for the paired difference, item bootstrap (10,000,
                 seed 42) cross-check; fixed-sequence H1 -> H2; S1-S8.

Dev (Stage A) is BLIND by default (§7 step 3): the full analysis runs (so the code path is
tested) but only the quantities the preregistration uses on dev are written: parse audit,
per-model accuracy / parse-failure rate (S6, M11 choice), yield y_A, discordance b+c
(direction-free) and the implied item count. No method accuracy, b-c or H1/H2 contrast is
written or printed. `--unblind` is refused for dev.

Usage
  python3 evaluate_v4.py --split dev  --bin <bran>                    # Stage A, blind
  python3 evaluate_v4.py --split conf --bin <bran> --m11-model <m>    # Stage B, once
  python3 evaluate_v4.py --selftest                                   # statistics self-test
"""

import argparse
import copy
import csv
import hashlib
import json
import math
import random
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
for p in (HERE / "benchmark" / "scripts", HERE / "canon", HERE / "power", EVAL / "v3", EVAL):
    sys.path.insert(0, str(p))
import answer_key as AK          # noqa: E402  frozen grader / parser
import canon as C                # noqa: E402  canon-1.0.0
import collect as c0             # noqa: E402  v3 claim extraction (unchanged)
import evaluate_v1 as v1         # noqa: E402
import evaluate_v2 as ev2        # noqa: E402
import evaluate_v3 as e3         # noqa: E402

MODELS = ["llama3.2:3b", "mistral", "gemma2:2b", "phi3:mini", "qwen2.5:3b"]
AGENTS = [m.replace(":", "_") for m in MODELS]
SPLIT_FILES = {"dev": "benchmark/items_dev.jsonl", "conf": "benchmark/items_confirmatory.jsonl"}
RUST_METHODS = ["M1", "M3", "M4", "M5", "M6"]
ALL_METHODS = ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10", "M11", "M12"]
DELTA_SEP = 0.05
BASE_W = [0.35, 0.2, 0.25, 0.05, 0.15]
REC0_W = [0.35, 0.2, 0.25, 0.0, 0.15]

# Policy overlays (on evaluate_v3.DEFAULT_POLICY; `values` filled per item).
POLICY_OVERLAYS = {
    "M1": {},
    "M3": {"weights": REC0_W, "schulze_dims": 23, "tiebreak_order": "id"},
    "M4": {"weights": REC0_W, "deadband_threshold": 0},
    "M5": {"weights": [1.0, 0.0, 0.0, 0.0, 0.0], "deadband_threshold": 0},
    "M6": {"weights": REC0_W, "deadband_threshold": 500, "tiebreak": "score_then_canonical"},
}

HEDGE_STRONG = re.compile(r'\b(might|may|could|possibly|perhaps|arguably|uncertain|debat)\b', re.I)
HEDGE_MOD = re.compile(r'\b(generally|typically|often|usually|tends? to|likely)\b', re.I)
CONF = {"HIGH": 0.85, "MEDIUM": 0.65, "LOW": 0.45}
SOURCE_LINE = re.compile(r'(?i)\b(sources?|references?|according to|cited?|citations?|et al\.?|doi|'
                         r'journal|study|studies|report|wikipedia|encyclop\w*)\b|https?://|www\.|\[\d+\]')


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def sha256_json(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def norm_obj(o):
    return " ".join(o.split()).lower()


def write_csv(path, rows, cols=None):
    cols = cols or (list(rows[0].keys()) if rows else [])
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


# ── statistics ──────────────────────────────────────────────────

def mcnemar_p(b, c):
    """v3 definition (evaluate_v2.mcnemar_exact)."""
    return ev2.mcnemar_exact(b, c)


def wilson(x, n, z=1.959963984540054):
    if n == 0:
        return 0.0, 1.0
    p = x / n
    den = 1 + z * z / n
    cen = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return cen - half, cen + half


def newcombe_paired(a, b, c, d):
    """Newcombe (1998) method 10 hybrid score CI for p1 - p2 with paired data.
    a: both correct, b: method 1 only, c: method 2 only, d: both wrong."""
    n = a + b + c + d
    if n == 0:
        return None
    p1, p2 = (a + b) / n, (a + c) / n
    l1, u1 = wilson(a + b, n)
    l2, u2 = wilson(a + c, n)
    den = (a + b) * (c + d) * (a + c) * (b + d)
    phi = (a * d - b * c) / math.sqrt(den) if den > 0 else 0.0
    dlt = math.sqrt(max((p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2, 0.0))
    eps = math.sqrt(max((u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2, 0.0))
    D = p1 - p2
    return [max(-1.0, D - dlt), min(1.0, D + eps)]


def bootstrap_diff(x, y, n_boot, seed):
    n = len(x)
    if n == 0:
        return None
    rng = random.Random(seed)
    diffs = []
    for _ in range(n_boot):
        s = 0
        for _ in range(n):
            i = rng.randrange(n)
            s += x[i] - y[i]
        diffs.append(s / n)
    diffs.sort()
    return [diffs[int(0.025 * n_boot)], diffs[min(n_boot - 1, int(0.975 * n_boot))]]


def paired(rows, m1, m2, args, with_boot=True):
    a = sum(1 for r in rows if r[m1] and r[m2])
    b = sum(1 for r in rows if r[m1] and not r[m2])
    c = sum(1 for r in rows if r[m2] and not r[m1])
    d = sum(1 for r in rows if not r[m1] and not r[m2])
    n = len(rows)
    out = {"n": n, "a": a, "b": b, "c": c, "d": d,
           "acc_" + m1: (a + b) / n if n else None, "acc_" + m2: (a + c) / n if n else None,
           "diff": (b - c) / n if n else None, "p_exact_mcnemar": mcnemar_p(b, c),
           "newcombe_ci95": newcombe_paired(a, b, c, d)}
    if with_boot:
        out["bootstrap_ci95"] = bootstrap_diff([r[m1] for r in rows], [r[m2] for r in rows],
                                               args.bootstrap, args.seed)
        out["bootstrap"] = {"resamples": args.bootstrap, "seed": args.seed, "unit": "item"}
    return out


def holm(pvals):
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m, run, out = len(items), 0.0, {}
    for k, (name, p) in enumerate(items):
        run = max(run, min(1.0, (m - k) * p))
        out[name] = run
    return out


def kappa(x, y):
    n = len(x)
    if n == 0:
        return None
    po = sum(1 for i in range(n) if x[i] == y[i]) / n
    px, py = sum(x) / n, sum(y) / n
    pe = px * py + (1 - px) * (1 - py)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


# ── loading ─────────────────────────────────────────────────────

def load_items(split):
    items = [json.loads(l) for l in open(HERE / SPLIT_FILES[split])]
    return {it["id"]: it for it in items}


def strip_answer_lines(text):
    return "\n".join(ln for ln in (text or "").splitlines() if not AK.ANSWER_RE.match(ln))


def hedge(line):
    if HEDGE_STRONG.search(line):
        return "LOW"
    if HEDGE_MOD.search(line):
        return "MEDIUM"
    return "HIGH"


def response_view(item, r):
    """Everything derived from one response (gold-blind except `correct`)."""
    text = r.get("raw_response") or ""
    line = AK.answer_line(text)
    obj = AK.parse_answer(item, text) if text else None
    body = strip_answer_lines(text)
    claims = c0.extract_claims_from_text(body, r["model"]) if body else []
    v1resp = {"agent": r["agent"], "model": r["model"], "raw_response": body, "claims": claims,
              "calibration": 0.7, "arrival_seq": r["arrival_seq"], "arrival_rank": r["arrival_rank"]}
    contribs = ev2.load_contributions([v1resp], associate=True)
    ev, seen = [], set()
    for c in contribs:
        for e in c.get("evidence", []):
            t = e.get("text", "")
            if t in seen:
                continue
            seen.add(t)
            ev.append({"type": e["type"], "weight": e["weight"], "text": t})
    src = [{"line_no": i, "text": ln} for i, ln in enumerate(text.splitlines())
           if ln.strip() and (SOURCE_LINE.search(ln) or v1._is_source_line(ln))
           and not AK.ANSWER_RE.match(ln)]
    return {"agent": r["agent"], "model": r["model"], "arrival_seq": r["arrival_seq"],
            "arrival_rank": r["arrival_rank"], "error": r.get("error"),
            "n_attempts": r.get("n_attempts"), "done_reason": (r.get("ollama_meta") or {}).get("done_reason"),
            "answer_line": line, "parsed": obj, "evidence": ev, "source_lines": src,
            "n_claims": len(claims), "v1resp": v1resp,
            "correct": bool(obj is not None and AK.grade(item, obj, line))}


def build_slot(item, views):
    parsed = [v for v in views if v["parsed"] is not None]
    contribs = []
    for v in parsed:
        cid = hashlib.sha256(f"{item['id']}|{v['agent']}|answer|{v['parsed']}".encode()).hexdigest()[:16]
        lc = hedge(v["answer_line"])
        contribs.append({"_id": cid, "agent": v["agent"], "subject": item["id"], "predicate": "answer",
                         "object": v["parsed"], "confidence": CONF[lc], "lowering_confidence": "HIGH",
                         "calibration": 0.7, "evidence": v["evidence"], "_seq": v["arrival_seq"] * 1000,
                         "raw_sentence": v["answer_line"], "_hedge": lc, "_correct": v["correct"],
                         "_line": v["answer_line"]})
    contribs.sort(key=lambda c: (c["_seq"], c["_id"]))
    return contribs


# ── Rust ────────────────────────────────────────────────────────

def policy(variant, contribs):
    p = copy.deepcopy(e3.DEFAULT_POLICY)
    p["values"]["incompatible_values"] = {
        "answer": {"__all_objects__": sorted({norm_obj(c["object"]) for c in contribs})}}
    p.update(copy.deepcopy(POLICY_OVERLAYS[variant]))
    return p


def run_rust(binary, item, contribs, variant, rdir):
    inp = {"intent": item["question"], "criteria": [], "calibration": {c["agent"]: 0.7 for c in contribs},
           "policy": policy(variant, contribs), "contributions": [e3.lower(c) for c in contribs]}
    d = rdir / item["id"]
    d.mkdir(parents=True, exist_ok=True)
    fin = d / f"{variant}.in.json"
    json.dump(inp, open(fin, "w"), indent=1, sort_keys=True)
    r = subprocess.run([binary, "--reduce", str(fin), "--no-color"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"bran --reduce failed on {fin}: {r.stderr}")
    out = json.loads(r.stdout)
    json.dump(out, open(d / f"{variant}.out.json", "w"), indent=1, sort_keys=True)
    return out


def rust_select(out):
    sel = [s for s in out["selections"] if s["type"] == "CONTRADICTION"]
    if len(sel) > 1:
        raise RuntimeError("more than one contradiction slot for one item")
    return sel[0] if sel else None


# ── Python mirror of the single-slot reduction (all AFFIRM, HIGH, no critiques) ──

def mirror(contribs, variant):
    pol = policy(variant, contribs)
    w, db = pol["weights"], pol["deadband_threshold"]
    mask = pol.get("schulze_dims", 31)
    tb, to = pol.get("tiebreak", "schulze"), pol.get("tiebreak_order", "seq")
    if len({norm_obj(c["object"]) for c in contribs}) < 2:
        return None
    mem = sorted(contribs, key=lambda c: (c["_seq"], c["_id"]))
    citers = defaultdict(set)
    for c in mem:
        for e in c["evidence"]:
            citers[e.get("text", "").lower()].add(c["agent"])
    n, denom = len(mem), max(len(mem) - 1, 1)
    sq, dims = {}, {}
    for rank, c in enumerate(mem):
        ev = e3.rust_ev(c, citers)
        conf = min(c["confidence"] * c["calibration"], 1.0)
        rec = rank / denom
        raw = w[0] * ev + w[1] * conf + w[2] * 1.0 + w[3] * rec + w[4] * 1.0
        sq[c["_id"]] = e3.q_round(raw * 1.0)
        dims[c["_id"]] = [e3.q_round(ev), e3.q_round(conf), e3.q_round(1.0), e3.q_round(rec), e3.q_round(1.0)]
    ids = [c["_id"] for c in mem]
    if to == "id":
        best = sorted(ids, key=lambda i: (-sq[i], i))[0]       # top score, ties by smallest id
    else:
        best = None
        for i in ids:
            if best is None or sq[i] > sq[best]:
                best = i
    top = sorted(sq.values(), reverse=True)
    inb = n >= 2 and top[0] - top[1] < db
    if inb and tb == "schulze":
        cand = [i for i in ids if top[0] - sq[i] < db]
        if to == "id":
            cand = sorted(cand)
        best = schulze_masked(cand, dims, mask, pol["schulze_dim_epsilon"])
    return {"members": ids, "winner": best, "scores_q": sq, "in_deadband": inb}


def schulze_masked(members, dims, mask, eps):
    n = len(members)
    if n < 2:
        return members[0]
    act = [k for k in range(5) if mask & (1 << k)]
    d = [[sum(1 for k in act if dims[members[i]][k] > dims[members[j]][k] + eps) if i != j else 0
          for j in range(n)] for i in range(n)]
    p = [row[:] for row in d]
    for k in range(n):
        for i in range(n):
            if i == k:
                continue
            for j in range(n):
                if j == i or j == k:
                    continue
                t = min(p[i][k], p[k][j])
                if t > p[i][j]:
                    p[i][j] = t
    best = 0
    for i in range(1, n):
        if p[i][best] > p[best][i]:
            best = i
    return members[best]


# ── per-item analysis ───────────────────────────────────────────

def object_correct(item, contribs, obj):
    """Grade a selected canonical object on its smallest-id member's ANSWER line."""
    holders = sorted((c for c in contribs if c["object"] == obj), key=lambda c: c["_id"])
    return int(AK.grade(item, obj, holders[0]["_line"])), len({c["_correct"] for c in holders}) > 1


def analyse_item(item, raw, binary, rdir, m11_agent):
    views = [response_view(item, r) for r in sorted(raw["responses"], key=lambda r: r["arrival_seq"])]
    contribs = build_slot(item, views)
    src = item["source"]["key"]
    row = {"id": item["id"], "source": src, "stratum": item["source"].get("stratum", ""),
           "answer_format": item["answer_format"], "n_responses": len(views),
           "n_parsed": len(contribs), "n_correct": sum(c["_correct"] for c in contribs)}
    row["eligible"] = int(len(contribs) >= 2)
    row["decisive"] = int(row["eligible"] and 0 < row["n_correct"] < len(contribs))
    rec = {"row": row, "views": views, "contribs": contribs}
    if not row["eligible"]:
        return rec
    by_id = {c["_id"]: c for c in contribs}
    outs, sels, mixed = {}, {}, 0
    for m in RUST_METHODS:
        out = run_rust(binary, item, contribs, m, rdir)
        outs[m] = out
        sel = rust_select(out)
        mir = mirror(contribs, m)
        if (sel is None) != (mir is None) or (sel is not None and (
                sel["winner"] != mir["winner"] or sel["in_deadband"] != mir["in_deadband"]
                or {k: int(v) for k, v in sel["scores_q"].items()} != mir["scores_q"]
                or sorted(sel["members"]) != sorted(mir["members"]))):
            raise SystemExit(f"ABORT: Python mirror != binary on {item['id']} {m}: {sel} vs {mir}")
        sels[m] = sel
        if sel is None:     # one distinct object: every method selects it
            o = contribs[0]["object"]
            row[m], mx = object_correct(item, contribs, o)
            row[m + "_obj"] = o
        else:
            w = by_id[sel["winner"]]
            row[m], row[m + "_obj"] = int(w["_correct"]), w["object"]
        row[m + "_policy_hash"] = out["policy_hash"]
    # M2 / M7 majority
    cnt = Counter(c["object"] for c in contribs)
    top = max(cnt.values())
    tied = sorted(o for o, k in cnt.items() if k == top)
    m2 = tied[0] if len(tied) == 1 else random.Random("v4-majority:" + item["id"]).choice(tied)
    first_arr = {o: min(c["_seq"] for c in contribs if c["object"] == o) for o in tied}
    m7 = min(tied, key=lambda o: first_arr[o])
    for m, o in (("M2", m2), ("M7", m7)):
        row[m], mx = object_correct(item, contribs, o)
        row[m + "_obj"] = o
        mixed += int(mx)
    row["majority_tied"] = int(len(tied) > 1)
    row["majority_top_count"] = top
    order = sorted(contribs, key=lambda c: (c["_seq"], c["_id"]))
    row["M8"], row["M9"] = int(order[0]["_correct"]), int(order[-1]["_correct"])
    pick = random.Random("v4-random:" + item["id"]).choice(sorted(contribs, key=lambda c: c["_id"]))
    row["M10"] = int(pick["_correct"])
    own = [c for c in contribs if c["agent"] == m11_agent]
    row["M11"] = int(own[0]["_correct"]) if own else row["M2"]
    row["M11_fallback"] = int(not own)
    row["M12"] = 1 if row["decisive"] else int(row["n_correct"] > 0)
    s1 = sels["M1"]
    row["in_deadband"] = int(bool(s1 and s1["in_deadband"]))
    row["M3_in_deadband"] = int(bool(sels["M3"] and sels["M3"]["in_deadband"]))
    row["mixed_objects"] = mixed
    rec.update(outs=outs, sels=sels, by_id=by_id)
    return rec


def margin_row(rec):
    """S4: on decisive items, evidence gap and total-score gap between the worst correct and the
    best incorrect member under M1 (ev = M5 score; lowering factor 1)."""
    row, s1, s5 = rec["row"], rec["sels"].get("M1"), rec["sels"].get("M5")
    out = {"id": row["id"], "source": row["source"], "M1_in_deadband": row["in_deadband"]}
    if s1 is None or s5 is None:
        out.update(status="no_rust_slot")
        return out
    by_id = rec["by_id"]
    corr = [i for i in s1["members"] if by_id[i]["_correct"]]
    inc = [i for i in s1["members"] if not by_id[i]["_correct"]]
    evg = min(s5["scores_q"][i] for i in corr) - max(s5["scores_q"][i] for i in inc)
    sg = min(s1["scores_q"][i] for i in corr) - max(s1["scores_q"][i] for i in inc)
    t2 = sorted(s1["scores_q"].values(), reverse=True)
    latest = 0
    if s1["in_deadband"]:
        cand = [i for i in s1["members"] if t2[0] - s1["scores_q"][i] < 500]
        latest = int(s1["winner"] == max(cand, key=lambda i: by_id[i]["_seq"]))
    out.update(status="ok", n_members=len(s1["members"]), n_correct=len(corr), n_incorrect=len(inc),
               ev_gap=round(evg / 10000, 6), ev_separated=int(evg / 10000 > DELTA_SEP),
               score_gap=round(sg / 10000, 6), score_separated=int(sg / 10000 > DELTA_SEP),
               top2_score_gap=round((t2[0] - t2[1]) / 10000, 6), deadband_winner_is_latest=latest)
    return out


# ── S1: free-text protocol arm (v3 pipeline + canon-1.0.0, readability triples) ──

S1_VARIANTS = {"forced": {}, "forced_m3": POLICY_OVERLAYS["M3"],
               "native": None, "native_m3": POLICY_OVERLAYS["M3"]}


def s1_policy(contribs, variant):
    p = copy.deepcopy(e3.DEFAULT_POLICY)
    iv = p["values"]["incompatible_values"]
    for pr in iv:
        for g in iv[pr]:
            iv[pr][g] = sorted({C.canon(o) for o in iv[pr][g]})
    if variant.startswith("forced"):
        groups = defaultdict(set)
        for c in contribs:
            groups[c["predicate"].lower()].add(norm_obj(c["object"]))
        p["values"]["incompatible_values"] = {pr: {"__all_objects__": sorted(o)} for pr, o in sorted(groups.items())}
    if variant.endswith("_m3"):
        p.update(copy.deepcopy(POLICY_OVERLAYS["M3"]))
    return p


def raw_view(c):
    c = dict(c)
    c["object"] = c.get("_raw_object", c["object"])
    return c


def s1_arm(items, recs, binary, sdir, args):
    qrows = {"A": [], "B": []}
    n_q = 0
    for rec in recs:
        item = items[rec["row"]["id"]]
        gt = [(g["subject"], g["predicate"], g["object"]) for g in item["gold_triples"] if g["predicate"] != "answer"]
        if not gt:
            continue                                    # SciFact: no readability triple
        resps = [v["v1resp"] for v in rec["views"] if v["v1resp"]["raw_response"]]
        if not resps:
            continue
        q = {"id": item["id"], "question": item["question"]}
        cs = e3.build_contribs(q, resps)
        for c in cs:
            c["_raw_object"] = c["object"]
            c["object"] = C.canon(c["object"])
        if not cs:
            continue
        n_q += 1
        by_id = {c["_id"]: c for c in cs}
        outs = {}
        for v in S1_VARIANTS:
            inp = {"intent": item["question"], "criteria": [], "calibration": {c["agent"]: c["calibration"] for c in cs},
                   "policy": s1_policy(cs, v), "contributions": [e3.lower(c) for c in cs]}
            d = sdir / item["id"]
            d.mkdir(parents=True, exist_ok=True)
            fin = d / f"{v}.in.json"
            json.dump(inp, open(fin, "w"), sort_keys=True)
            r = subprocess.run([binary, "--reduce", str(fin), "--no-color"], capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(r.stderr)
            outs[v] = json.loads(r.stdout)
        for gname, grader in ev2.GRADERS.items():
            corr = lambda c: ev2.correct_any(raw_view(c), gt, grader)  # noqa: E731
            for cset in v1.detect_conflicts(cs):            # Table A: Python-structured slots
                if cset["type"] != "contradiction":
                    continue
                mem = cset["members"]
                fl = [corr(m) for m in mem]
                if not any(fl):
                    continue
                ids = [m["_id"] for m in mem]
                row = {"id": item["id"], "source": item["source"]["key"], "grader": gname,
                       "n_members": len(mem), "decisive": int(not all(fl))}
                for col, var in (("M1", "forced"), ("M3", "forced_m3")):
                    kind, adm, _ = e3.rust_outcome(ids, outs[var])
                    row[col] = int(bool(adm) and all(corr(by_id[i]) for i in adm))
                row["M2"] = int(fl[ev2.majority_idx(mem)])
                qrows["A"].append(row)
            sels = {v: {frozenset(s["members"]): s for s in outs[v]["selections"] if s["type"] == "CONTRADICTION"}
                    for v in ("native", "native_m3")}
            for fk, s in sels["native"].items():          # Table B: Rust-native slots
                mem = [by_id[i] for i in s["members"]]
                fl = {i: corr(by_id[i]) for i in s["members"]}
                if not any(fl.values()):
                    continue
                s3 = sels["native_m3"].get(fk)
                qrows["B"].append({"id": item["id"], "source": item["source"]["key"], "grader": gname,
                                   "n_members": len(mem), "decisive": int(not all(fl.values())),
                                   "M1": int(fl[s["winner"]]),
                                   "M3": int(fl[s3["winner"]]) if s3 else None,
                                   "M2": int(list(fl.values())[ev2.majority_idx(mem)])})
    res = {"items_with_readability_triples_and_claims": n_q, "graders": {"v2": "stricter (primary for S1)", "v1": "original"}}
    for t, rows in qrows.items():
        for g in ev2.GRADERS:
            sub = [r for r in rows if r["grader"] == g]
            dec = [r for r in sub if r["decisive"] and r["M3"] is not None]
            res[f"{t}|{g}"] = {"eligible_sets": len(sub), "decisive_sets": len(dec),
                               "decisive_items": len({r["id"] for r in dec}),
                               "M3_vs_M2": paired(dec, "M3", "M2", args, with_boot=False) if dec else None,
                               "M3_vs_M1": paired(dec, "M3", "M1", args, with_boot=False) if dec else None}
    return res, qrows


# ── Stage A stopping rule (§7 step 4) ───────────────────────────

def stopping_rule(y, psi):
    import power as PW
    psi_star = max(psi, 0.25)
    n_exact = PW.min_n_stable(psi_star, 0.10)
    table = {0.15: 122, 0.20: 168, 0.25: 207, 0.30: 249, 0.35: 289, 0.40: 329, 0.50: 408, 0.60: 487, 0.70: 566}
    col = min((k for k in table if k >= psi_star - 1e-12), default=None)
    out = {"psi_star": psi_star, "N_star_exact_min_n_stable": n_exact,
           "N_star_table1_next_column": {"psi_column": col, "N": table.get(col)}}

    def items_for(N):
        if not y:
            return {"I_unclamped": None, "I": 1000, "exceeds_cap": True}
        raw_i = 4 * math.ceil(N / (4 * y))
        return {"I_unclamped": raw_i, "I": min(max(raw_i, 600), 1000), "exceeds_cap": raw_i > 1000}
    out["I_from_exact"] = items_for(n_exact)
    if table.get(col):
        out["I_from_table_column"] = items_for(table[col])
    return out


# ── main ────────────────────────────────────────────────────────

def provenance(binary):
    freeze = json.load(open(HERE / "FREEZE.json"))
    bad = [p for p, h in freeze["sha256"].items() if sha256_file(HERE / p) != h]
    if bad:
        raise SystemExit(f"ABORT: FREEZE.json mismatch: {bad}")
    return {"binary": binary, "binary_sha256": sha256_file(binary),
            "build_provenance": json.load(open(HERE / "results" / "build_provenance.json"))
            if (HERE / "results" / "build_provenance.json").exists() else None,
            "evaluate_v4_py_sha256": sha256_file(__file__),
            "collect_v4_py_sha256": sha256_file(HERE / "collect_v4.py"),
            "FREEZE.json_sha256": sha256_file(HERE / "FREEZE.json"), "freeze_verified": sorted(freeze["sha256"]),
            "canon": AK.canon_provenance(), "evaluate_v3_py_sha256": sha256_file(EVAL / "v3" / "evaluate_v3.py"),
            "evaluate_v2_py_sha256": sha256_file(EVAL / "evaluate_v2.py"),
            "collect_py_sha256": sha256_file(EVAL / "collect.py"),
            "policy_overlays": POLICY_OVERLAYS,
            "policy_overlay_sha256": {m: sha256_json(POLICY_OVERLAYS[m]) for m in POLICY_OVERLAYS},
            "base_policy": e3.DEFAULT_POLICY}


def per_model(recs):
    out = {}
    for a in AGENTS:
        vs = [v for r in recs for v in r["views"] if v["agent"] == a]
        n = len(vs)
        out[a] = {"responses": n, "errors": sum(1 for v in vs if v["error"]),
                  "no_answer_line": sum(1 for v in vs if v["answer_line"] is None and not v["error"]),
                  "unparseable": sum(1 for v in vs if v["parsed"] is None),
                  "parse_failure_rate": (sum(1 for v in vs if v["parsed"] is None) / n) if n else None,
                  "truncated_length": sum(1 for v in vs if v["done_reason"] == "length"),
                  "correct": sum(1 for v in vs if v["correct"]),
                  "accuracy_all_items": (sum(1 for v in vs if v["correct"]) / n) if n else None,
                  "by_source_unparseable": dict(Counter(r["row"]["source"] for r in recs for v in r["views"]
                                                        if v["agent"] == a and v["parsed"] is None))}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "conf"])
    ap.add_argument("--bin")
    ap.add_argument("--raw-dir", help="override results/<split>/raw (testing)")
    ap.add_argument("--out", help="override results/<split>/ (testing)")
    ap.add_argument("--m11-model", help="agent id for M11 (conf: required; fixed from Stage A)")
    ap.add_argument("--bootstrap", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--unblind", action="store_true", help="conf only")
    ap.add_argument("--labels", help="human PopQA labels CSV (id,agent,human_correct) for S7")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--synthetic-test", action="store_true",
                    help="unblinded run on SYNTHETIC raw records only (raw dir must contain a SYNTHETIC marker)")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not (args.split and args.bin):
        ap.error("--split and --bin are required")
    blind = args.split == "dev"
    if args.synthetic_test:
        if not (args.raw_dir and (Path(args.raw_dir) / "SYNTHETIC").exists()):
            raise SystemExit("refused: --synthetic-test needs --raw-dir with a SYNTHETIC marker file")
        blind = False
    if blind and args.unblind:
        raise SystemExit("refused: dev (Stage A) analysis is blind by preregistration (§7 step 3)")
    if args.split == "conf":
        freeze = json.load(open(HERE / "FREEZE.json"))["sha256"]
        if freeze.get("evaluate_v4.py") != sha256_file(__file__):
            raise SystemExit("ABORT: evaluate_v4.py is not frozen by hash in FREEZE.json (required before Stage B)")
        if not args.m11_model:
            raise SystemExit("ABORT: --m11-model (fixed from Stage A) is required for conf")
    prov = provenance(args.bin)
    out_dir = Path(args.out).resolve() if args.out else HERE / "results" / args.split
    raw_dir = Path(args.raw_dir).resolve() if args.raw_dir else out_dir / "raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    items = load_items(args.split)
    raws = {f.stem: json.load(open(f)) for f in sorted(raw_dir.glob("v4-*.json"))}
    ids = sorted(raws, key=lambda i: items[i]["order"])

    # S6 first (it fixes M11 on dev)
    views_only = [{"row": {"id": i, "source": items[i]["source"]["key"]},
                   "views": [response_view(items[i], r) for r in raws[i]["responses"]]} for i in ids]
    pm = per_model(views_only)
    if args.m11_model:
        m11 = args.m11_model.replace(":", "_")
    else:
        m11 = max(AGENTS, key=lambda a: (pm[a]["correct"], -AGENTS.index(a)))

    # Rust I/O and S1 scratch: blind runs keep selections out of the results tree
    tmp = Path(tempfile.mkdtemp(prefix="v4eval-")) if blind else None
    rdir = (tmp / "rust") if blind else out_dir / "rust"
    sdir = (tmp / "s1") if blind else out_dir / "s1_rust"
    recs = [analyse_item(items[i], raws[i], args.bin, rdir, m11) for i in ids]
    rows = [r["row"] for r in recs]
    elig = [r for r in rows if r["eligible"]]
    dec = [r for r in rows if r["decisive"]]
    n_items = len(rows)

    # responses (gold-blind fields + G-AK verdict) and parse audit
    resp_rows = []
    for rec in recs:
        for v in rec["views"]:
            resp_rows.append({"id": rec["row"]["id"], "source": rec["row"]["source"], "agent": v["agent"],
                              "arrival_seq": v["arrival_seq"], "arrival_rank": v["arrival_rank"],
                              "error": v["error"], "n_attempts": v["n_attempts"], "done_reason": v["done_reason"],
                              "answer_line": v["answer_line"], "parsed": v["parsed"], "gak_correct": int(v["correct"]),
                              "n_claims": v["n_claims"], "n_evidence": len(v["evidence"]),
                              "evidence": v["evidence"], "source_lines": v["source_lines"]})
    with open(out_dir / "responses_v4.jsonl", "w") as f:
        for r in resp_rows:
            f.write(json.dumps(r) + "\n")
    write_csv(out_dir / "parse_audit_v4.csv", [{k: r[k] for k in r if k not in ("evidence", "source_lines")}
                                               for r in resp_rows])
    # S7 labeling sheet: every PopQA answer line (blind to the G-AK verdict)
    sheet = [{"id": r["id"], "agent": r["agent"], "question": items[r["id"]]["question"],
              "gold_answer": items[r["id"]]["gold"]["answer"], "gold_aliases": " | ".join(items[r["id"]]["gold"]["aliases"]),
              "answer_line": r["answer_line"] or "", "human_correct": ""}
             for r in resp_rows if r["source"] == "popqa" and r["answer_line"]]
    write_csv(out_dir / "popqa_label_sheet.csv", sheet)

    # stopping-rule quantities (direction-free)
    disc_m1m2 = sum(1 for r in dec if r["M1"] != r["M2"])
    disc_m3m2 = sum(1 for r in dec if r["M3"] != r["M2"])
    y = len(dec) / n_items if n_items else 0.0
    psi_a = disc_m1m2 / len(dec) if dec else 0.0
    psi_h1 = disc_m3m2 / len(dec) if dec else 0.0
    res = {"split": args.split, "blind": blind, "provenance": prov, "n_items": n_items,
           "n_raw_files": len(raws),
           "exclusions_fewer_than_2_parseable": dict(Counter(r["source"] for r in rows if not r["eligible"])),
           "eligible": len(elig), "decisive": len(dec),
           "decisive_by_source": dict(Counter(r["source"] for r in dec)),
           "eligible_by_source": dict(Counter(r["source"] for r in elig)),
           "yield_y": y,
           "discordance": {"M1_vs_M2_b_plus_c": disc_m1m2, "psi_M1_M2": psi_a,
                           "M3_vs_M2_b_plus_c": disc_m3m2, "psi_M3_M2": psi_h1},
           "stopping_rule": {"prereg_text_M1_vs_M2": stopping_rule(y, psi_a),
                             "H1_pair_M3_vs_M2": stopping_rule(y, psi_h1)},
           "per_model_S6": pm, "M11_model": m11,
           "M11_rule": "agent with most G-AK-correct answers over all dev items (unparseable = wrong); ties -> v3 list order",
           "objects_with_mixed_member_correctness": sum(r.get("mixed_objects", 0) for r in elig),
           "mirror_check": {"slots_checked": len(elig) * len(RUST_METHODS), "mismatches": 0},
           "policy_hashes_distinct": {m: len({r[m + "_policy_hash"] for r in elig}) for m in RUST_METHODS},
           "policy_hash_first_item": {m: (elig[0][m + "_policy_hash"] if elig else None) for m in RUST_METHODS}}
    blind_cols = ["id", "source", "stratum", "answer_format", "n_responses", "n_parsed", "n_correct",
                  "eligible", "decisive"]
    write_csv(out_dir / "items_v4_blind.csv", rows, blind_cols)
    write_csv(out_dir / "policy_hashes_v4.csv", [{"id": r["id"], **{m: r[m + "_policy_hash"] for m in RUST_METHODS}}
                                                 for r in elig])

    full = analysis(items, recs, elig, dec, args, sdir)      # always computed (code path test)
    if blind:
        shutil.rmtree(tmp, ignore_errors=True)
        res["full_analysis_computed_not_written"] = sorted(full.keys())
        json.dump(res, open(out_dir / "stage_a_v4.json", "w"), indent=2)
        print(json.dumps({k: res[k] for k in ("n_items", "eligible", "decisive", "yield_y", "discordance",
                                               "stopping_rule", "M11_model")}, indent=1))
        return
    res.update(full)
    write_csv(out_dir / "paired_decisions_v4.csv", elig,
              ["id", "source", "stratum", "n_parsed", "n_correct", "decisive", "in_deadband"] + ALL_METHODS)
    write_csv(out_dir / "separation_margins_v4.csv", full.pop("_margins"))
    res.pop("_margins", None)
    json.dump(res, open(out_dir / "evaluation_v4.json", "w"), indent=2)
    print(json.dumps(res["H1"], indent=1))


def analysis(items, recs, elig, dec, args, sdir):
    out = {}
    h1 = paired(dec, "M3", "M2", args)
    h1["reject"] = h1["p_exact_mcnemar"] <= 0.05
    out["H1"] = {"contrast": "M3 (order-free Bran) vs M2 (canonical majority), decisive conflicts", **h1}
    h2 = paired(dec, "M3", "M1", args)
    lo = h2["newcombe_ci95"][0] if h2["newcombe_ci95"] else None
    h2["noninferiority_margin"] = -0.10
    h2["noninferior"] = bool(lo is not None and lo > -0.10)
    h2["superior"] = bool(h2["noninferior"] and h2["p_exact_mcnemar"] <= 0.05 and h2["b"] > h2["c"])
    h2["status"] = "confirmatory" if h1["reject"] else "exploratory (H1 not rejected; §9)"
    out["H2"] = {"contrast": "M3 vs M1 (non-inferiority, margin -0.10, one-sided 0.025 via the 95% Newcombe "
                             "lower bound; then superiority by exact McNemar)", **h2}
    out["S2_accuracy_eligible"] = {m: sum(r[m] for r in elig) / len(elig) if elig else None for m in ALL_METHODS}
    out["accuracy_decisive"] = {m: sum(r[m] for r in dec) / len(dec) if dec else None for m in ALL_METHODS}
    s3 = {}
    for key in ("source", "stratum"):
        for g in sorted({r[key] for r in dec if r[key]}):
            sub = [r for r in dec if r[key] == g]
            s3[f"{key}={g}"] = {"n": len(sub), **{m: sum(r[m] for r in sub) / len(sub) for m in ALL_METHODS},
                                "M3_vs_M2": paired(sub, "M3", "M2", args, with_boot=False)}
    out["S3"] = s3
    margins = [margin_row(r) for r in recs if r["row"]["decisive"]]
    ok = [m for m in margins if m["status"] == "ok"]
    out["S4"] = {"decisive": len(margins), "with_rust_slot": len(ok),
                 "ev_separated": sum(m["ev_separated"] for m in ok),
                 "score_separated": sum(m["score_separated"] for m in ok), "delta": DELTA_SEP}
    db = [r for r in elig if r["in_deadband"]]
    lat = {m["id"]: m.get("deadband_winner_is_latest", 0) for m in margins}
    out["S5"] = {"M1_deadband_entry_eligible": len(db) / len(elig) if elig else None,
                 "M1_deadband_entry_decisive": sum(r["in_deadband"] for r in dec) / len(dec) if dec else None,
                 "M3_deadband_entry_eligible": sum(r["M3_in_deadband"] for r in elig) / len(elig) if elig else None,
                 "M1_decisive_deadband_winner_is_latest": sum(lat.get(r["id"], 0) for r in dec if r["in_deadband"]),
                 "M1_decisive_in_deadband": sum(r["in_deadband"] for r in dec)}
    s1, _ = s1_arm(items, recs, args.bin, sdir, args)
    out["S1"] = s1
    s8 = {m: paired(dec, m, "M1", args, with_boot=False) for m in ALL_METHODS[2:11]}
    hp = holm({m: s8[m]["p_exact_mcnemar"] for m in s8})
    for m in s8:
        s8[m]["p_holm"] = hp[m]
    out["S8"] = s8
    out["M11_fallbacks_decisive"] = sum(r["M11_fallback"] for r in dec)
    out["majority_tied_decisive"] = sum(r["majority_tied"] for r in dec)
    if args.labels:
        lab = {(r["id"], r["agent"]): int(r["human_correct"]) for r in csv.DictReader(open(args.labels))
               if r.get("human_correct", "") != ""}
        resp = {(r["row"]["id"], v["agent"]): int(v["correct"]) for r in recs for v in r["views"]}
        keys = sorted(k for k in lab if k in resp)
        out["S7"] = {"n": len(keys), "kappa": kappa([lab[k] for k in keys], [resp[k] for k in keys]),
                     "agreement": sum(lab[k] == resp[k] for k in keys) / len(keys) if keys else None}
    out["_margins"] = margins
    return out


def selftest():
    # McNemar (v3 definition) and Newcombe against hand-checked values
    assert mcnemar_p(0, 0) == 1.0
    assert abs(mcnemar_p(2, 8) - 0.109375) < 1e-12
    # Newcombe hybrid score CI: properties (bounds ordered and contain D; mirror symmetry
    # b<->c; phi = 0 reduces to the unpaired Newcombe-Wilson interval)
    for a, b, c, d in [(1, 2, 8, 10), (12, 9, 2, 21), (0, 5, 0, 5), (40, 3, 3, 4)]:
        lo, hi = newcombe_paired(a, b, c, d)
        D = (b - c) / (a + b + c + d)
        assert lo <= D <= hi and -1 <= lo and hi <= 1, (a, b, c, d, lo, hi)
        lo2, hi2 = newcombe_paired(a, c, b, d)
        assert abs(lo + hi2) < 1e-12 and abs(hi + lo2) < 1e-12
    bs = bootstrap_diff([1, 0, 1, 1, 0] * 20, [0, 0, 1, 0, 1] * 20, 2000, 42)
    assert bs[0] < 0.2 < bs[1]
    assert holm({"a": 0.01, "b": 0.04, "c": 0.03}) == {"a": 0.03, "b": 0.06, "c": 0.06}
    assert abs(kappa([1, 1, 0, 0], [1, 0, 0, 0]) - 0.5) < 1e-12
    print("evaluate_v4 selftest ok")


if __name__ == "__main__":
    main()
