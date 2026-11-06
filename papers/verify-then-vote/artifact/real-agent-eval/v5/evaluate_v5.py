#!/usr/bin/env python3
"""
Eval v5 analysis (v3/SWARM3_DESIGN.md §1, §3.3-§3.4, §5, §6.2; swarm-3 lane L7).

Inputs (the interface contract with L2/L3/L5/L6; one set per split):
  --items     items JSONL (L4; v4 item schema, plus `source.subj` for PopQA)
  --raw-dir   <id>.json per item (L3): {"id", "responses": [{agent, model, arrival_seq,
              arrival_rank, closed_book, query, retrieval: bran-retrieval/1, answer_json,
              raw_response, error, done_reason}]}
  --captures  JSONL (L2): {"passage_key", "capture_id", "record": bran-capture/1}; impossible
              citation labels are captured under the label itself (invalid_identifier)
  --checks    JSONL (L5): one de-duplicated (proposition, passage) check:
              {"check_key", "proposition_key", "proposition_text", "passage_key", "capture_id",
               "status", "label" (raw, on the proposition), "score_q", "raw_output_sha256",
               "spans", "span_selector"?, "checker": Rust Checker block,
               "cost_usd"?, "duration_ms"?, "input_tokens"?, "output_tokens"?}
  --judge     JSONL (L6): {"id", "method": "J"|"RS", "run": 0|1, "status", "selected",
               "input_tokens", "output_tokens", "usd", "wall_ms"}

Pipeline per item
  1. parse     the structured answer (§3.3; strict schema: reasoning, answer, citations,
               confidence). Eligible: >= 2 parsed. Decisive: eligible, >= 1 correct and
               >= 1 incorrect under G-AK (v4 answer_key.grade, unchanged; method-blind).
  2. lower     one AFFIRM triple (v5-<id>, answer, <canonical value>) per parsed answer;
               raw_text = the §3.4 proposition (tools/evidence/support/propositions.py), so the
               checker's claim is sealed with the record; confidence high .85 / medium .65 /
               low .45; calibration 0.7; seq = arrival_seq*1000; one CITATION (weight 1.0) per
               cited passage with capture_ref, and support_ref -> a bran-support/1 record whose
               label is the checker label mapped to this value (binary REFUTED: swapped).
  3. reduce    `bran --reduce` per Rust method: B0 (v4 M3), the six BE grid configurations
               (dev) or the frozen one (conf), EO; a Python mirror of the selection must equal
               the binary on every slot (abort on mismatch); BE is reduced twice and the two
               outputs must be byte-identical (replay identity, H3).
  4. python    MAJ, VV, BEST, ORC, and J / RS from the sealed judge outputs.
  5. stats     H1 exact McNemar on (b, c), Newcombe CI, item bootstrap (10,000, seed 42),
               p_w and q_r with Wilson CIs; H2 non-inferiority (margin -0.05 via the Newcombe
               lower bound, one-sided 0.025), superiority only if NI holds; H3 costs, replay,
               J drift; dev gate (§6.2) and stopping rule.

Preregistered analysis (real-agent-eval/v5/PREREGISTRATION.md §2, §7, §10, §11), in both splits
(on dev it is dev-informed and descriptive), under the `prereg` key of evaluation_v5.json:
  sets     P (tier `primary`, SciFact/PopQA/FEVER) and T (tier `tqa_stratum`, TruthfulQA), never
           pooled for a test; on items without those tiers (dev) T = TruthfulQA, P = the rest.
  H1       H1a BE-G vs MAJ, H1b BE vs MAJ on P, exact McNemar, Holm (family-wise 0.05).
  H3       H3a: one-sided 97.5% Clopper-Pearson upper bound on c/n_R (P, MAJ right) < 0.05;
           H3b: T, BE-G vs MAJ non-inferiority, Newcombe lower bound > -0.03. BE descriptive.
  H2       local arm, fixed sequence H2a (BE-G-L vs MAJ) -> H2b-NI (vs J_local, -0.05) -> H2b-S;
           `--local-arm confirmatory|exploratory`, plus J_local self-preference / shared model.
  refs     J, RS, CB-S, CV, CONF vs MAJ and vs BE-G (exact McNemar; Holm-adjusted vs MAJ).
  H4       c_D, F, F items, harm_bound_holds, F-hat from the validation false-support rate.
  H5       gap-closed fraction (REF in {J, ORC}, item bootstrap), uniform cost basis on every
           disagreement item ($, calls, tokens, cache-creation tokens, local wall time), latency,
           replay identity (BE-G, BE, BE-G-L), J regeneration, J_local drift, leave-one-agent-out,
           audit size, majority-following, subgroups, sensitivity analyses, figure data.

Usage
  python3 evaluate_v5.py --split dev  --bin <bran> --items .. --raw-dir .. --captures .. \
      --checks .. --judge .. --accepted-checker <id> --out <dir>
  python3 evaluate_v5.py --split conf ... --be-g-config member/nei0.5/gated --be-config member/nei0.1 \
      --best-model mistral [--local-checks .. --local-accepted-checker <id> --local-arm confirmatory \
      --judge-local .. --expect-template BE-G-L=<sha256>]
  python3 evaluate_v5.py --selftest
"""

import argparse
import copy
import csv
import hashlib
import json
import math
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
ROOT = EVAL.parent
V4 = EVAL / "v4"
for p in (HERE / "power", ROOT / "tools" / "evidence", ROOT / "tools" / "evidence" / "support"):
    sys.path.insert(0, str(p))
# appended, not prepended: v4/canon holds other scripts (make_results.py) that must not shadow v5's
for p in (V4 / "benchmark" / "scripts", V4 / "canon"):
    sys.path.append(str(p))
import answer_key as AK          # noqa: E402  frozen G-AK grader (v4)
import canon as C                # noqa: E402  canon-1.0.0
import corpus_capture as CC      # noqa: E402  L2: citation labels -> passage keys
import propositions as PR        # noqa: E402  L5: §3.4 renderer + label maps
from canonical import record_id  # noqa: E402

FORMAT = "bran-eval-v5/1"
CONF = {"high": 0.85, "medium": 0.65, "low": 0.45}
CALIBRATION = 0.7
SEP_DELTA_Q = 500                 # S4 separation threshold 0.05 on the 10,000 scale
NI_MARGIN = -0.05
REC0_W = [0.35, 0.2, 0.25, 0.0, 0.15]
# evaluate_v3.DEFAULT_POLICY, copied verbatim (test_evaluate_v5 asserts equality)
BASE_POLICY = {
    "deadband_threshold": 500,
    "hardening": {"max_critiques_per_agent": 3, "min_corroboration": 2,
                  "reject_uncorroborated": False, "singleton_score_penalty": 0.0},
    "max_severity_budget": 5.0,
    "schulze_dim_epsilon": 100,
    "values": {"incompatible_values": {
        "detects_corruption_via": {"tcp_integrity_check": ["16-bit checksum", "crc-32"]},
        "handles_loss_via": {"tcp_loss_recovery": ["forward error correction (fec)",
                                                   "retransmission with exponential backoff"]},
        "uses": {"tcp_handshake": ["three-way handshake (syn, syn-ack, ack)", "two-way handshake"]},
    }},
    "weights": [0.35, 0.2, 0.25, 0.05, 0.15],
}
M3_OVERLAY = {"weights": REC0_W, "schulze_dims": 23, "tiebreak_order": "id"}   # v4 M3 = B0
MODES = ["member", "value:max", "value:pooled"]
NEIS = [0.5, 0.1]
GRID = [f"{m}/nei{n}" for m in MODES for n in NEIS]      # §5.1, fixed order (final tie-break)
# FRAMING §3.4 grid additions: NEI factor 0 and the verified-overturn gate (Rust
# `evidence.overturn_gate = "verified"`, v3/GATE_SPEC.md). They were added after inspecting
# dev c-cases, so they are dev_informed: never eligible for the §5.1 BE selection, and dev
# data provide no evidence for them. Full grid order (final tie-break of the gated selection):
# gate {off, verified} x mode x NEI {0.5, 0.1, 0}.
NEIS_ALL = [0.5, 0.1, 0.0]
GATED = "/gated"
FULL_GRID = [f"{m}/nei{n:g}{g}" for g in ("", GATED) for m in MODES for n in NEIS_ALL]
DEV_INFORMED = [c for c in FULL_GRID if c not in GRID]
GATED_GRID = [c for c in FULL_GRID if c.endswith(GATED)]
UNCHECKED_FACTOR = 0.5                                    # §2.4 item 6
SEALABLE = {"ok": "ok", "parse_error": "parse_error", "input_too_long": "input_too_long",
            "model_mismatch": "model_mismatch", "refused": "parse_error"}   # check.py RECORD_STATUS
DEFAULT_SPAN_SELECTOR = {"method": "bm25/1", "version": "1",
                         "params": {"k1_x1000": 1200, "b_x1000": 750, "chunk_chars": 1000, "overlap_chars": 200}}
METHODS = ["MAJ", "BEST", "B0", "BE", "EO", "VV", "J", "RS", "ORC"]
GATE = {"yield": 0.30, "m": 0.20, "evidence_availability": 0.30, "parse_failure": 0.05}
Z = 1.959963984540054

# ── PREREGISTRATION.md constants (§2, §5, §12) ──
PREREG_CHECKER = "f2a14bd8988371bd231ca6ff137be13e"            # hosted checker 0.2.0
PREREG_CONFIGS = {"BE-G": "member/nei0.5/gated", "BE": "member/nei0.1"}
PREREG_BEST = "mistral"
PREREG_TEMPLATES = {                                             # valid with accepted = [PREREG_CHECKER]
    "BE-G": "99c8b9c91c27d4fcf8cb33be2f342eb6dffa175f10802459df52a23ee2a0a245",
    "BE": "084ecdbdcd06193beab228fc9ca21fcf1842f1fffd0326052c5b8908581dada0",
    "EO": "75ee3a54eb249c59a911bd75739f2ad06b6ba924e822e383a7f50f2ed6eb7ac7",
    "B0": "e08f2ea6ad5c6fdeb36f8eeee2dce1555d6ba9450b25625945128bc06ad25f16",
}
PREREG_JUDGE_IDS = {"J": "4f8c27d90e3c1230dd9b9a91d30530f1", "RS": "108a3dee08e1b4286ea879ee070ce4bb"}
# §2.5: pooled non-supports -> supports rate of the accepted checker's validation report
FHAT_RATE = {PREREG_CHECKER: (18, 350)}
H1_ALPHA = 0.05
H3A_BOUND, H3A_ALPHA = 0.05, 0.025
H3B_MARGIN = -0.03
H2_ALPHA, H2_NI_MARGIN = 0.05, -0.05
SETS = ("P", "T", "pooled")
GAP_METHODS = ["BE-G", "BE", "BE-G-L", "VV", "EO"]
GAP_REFS = ["J", "ORC"]
REF_FAMILY = ["J", "RS", "CB-S", "CV", "CONF"]                   # §2.4, Holm-adjusted vs MAJ
JUDGES = ["J", "RS", "CB-S", "J_local"]
N_JREGEN, N_LOAO_J, N_WITNESS = 200, 50, 100



def jload(p):
    with open(p) as f:
        return json.load(f)

def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def sha256_json(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def norm_obj(o):
    return " ".join(o.split()).lower()


def write_csv(path, rows, cols):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


# ── statistics (v4 definitions) ─────────────────────────────────

def mcnemar_p(b, c):
    """Exact two-sided McNemar, v3 definition (evaluate_v2.mcnemar_exact)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def wilson(x, n, z=Z):
    if n == 0:
        return None
    p = x / n
    den = 1 + z * z / n
    cen = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [max(0.0, cen - half), min(1.0, cen + half)]


def newcombe_paired(a, b, c, d):
    """Newcombe (1998) method 10 hybrid score CI for p1 - p2, paired (as evaluate_v4)."""
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
    if n == 0 or n_boot <= 0:
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


def paired(rows, m1, m2, n_boot=0, seed=42):
    a = sum(1 for r in rows if r[m1] and r[m2])
    b = sum(1 for r in rows if r[m1] and not r[m2])
    c = sum(1 for r in rows if r[m2] and not r[m1])
    d = sum(1 for r in rows if not r[m1] and not r[m2])
    n = len(rows)
    out = {"method": m1, "baseline": m2, "n": n, "a": a, "b": b, "c": c, "d": d,
           "acc_method": (a + b) / n if n else None, "acc_baseline": (a + c) / n if n else None,
           "diff": (b - c) / n if n else None, "psi": (b + c) / n if n else None,
           "p_exact_mcnemar": mcnemar_p(b, c), "newcombe_ci95": newcombe_paired(a, b, c, d)}
    if n_boot:
        out["bootstrap_ci95"] = bootstrap_diff([r[m1] for r in rows], [r[m2] for r in rows], n_boot, seed)
        out["bootstrap"] = {"resamples": n_boot, "seed": seed, "unit": "item"}
    return out


def overturn(rows, m, base="MAJ"):
    """b, c, p_w = b/#(base wrong), q_r = c/#(base right), with Wilson CIs."""
    nw = sum(1 for r in rows if not r[base])
    nr = len(rows) - nw
    b = sum(1 for r in rows if r[m] and not r[base])
    c = sum(1 for r in rows if not r[m] and r[base])
    return {"method": m, "n": len(rows), "base_wrong": nw, "base_right": nr, "b": b, "c": c,
            "net_gain": (b - c) / len(rows) if rows else None,
            "p_w": b / nw if nw else None, "p_w_wilson95": wilson(b, nw),
            "q_r": c / nr if nr else None, "q_r_wilson95": wilson(c, nr)}


def noninferiority(pair, margin=NI_MARGIN):
    lo = pair["newcombe_ci95"][0] if pair["newcombe_ci95"] else None
    ni = bool(lo is not None and lo > margin)
    sup = bool(ni and pair["p_exact_mcnemar"] <= 0.05 and pair["b"] > pair["c"])
    return {"margin": margin, "one_sided_alpha": 0.025, "newcombe_lower": lo, "noninferior": ni,
            "superiority_tested": ni, "superior": sup}


def binom_cdf(k, n, p):
    """P(X <= k), X ~ Binom(n, p) (log-space terms; exact enough for n in the thousands)."""
    if k < 0:
        return 0.0
    if k >= n or p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 0.0
    lp, lq = math.log(p), math.log1p(-p)
    ln = math.lgamma(n + 1)
    s = sum(math.exp(ln - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq) for i in range(k + 1))
    return min(1.0, s)


def cp_upper(x, n, alpha=H3A_ALPHA):
    """One-sided (1 - alpha) Clopper-Pearson upper bound on x/n: the p with P(X <= x; n, p) = alpha."""
    if n == 0:
        return None
    if x >= n:
        return 1.0
    lo, hi = x / n, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if binom_cdf(x, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return hi


def holm(pvals, alpha=0.05):
    """Holm step-down over {name: p}. Ties in p are ordered by name. Returns {name: {p, p_holm,
    rank, threshold, reject}}; a hypothesis is rejected only if every smaller p was rejected."""
    order = sorted(pvals, key=lambda k: (pvals[k], k))
    m = len(order)
    out, running, still = {}, 0.0, True
    for i, k in enumerate(order):
        thr = alpha / (m - i)
        running = max(running, min(1.0, (m - i) * pvals[k]))
        still = still and pvals[k] <= thr
        out[k] = {"p": pvals[k], "p_holm": running, "rank": i + 1, "threshold": thr, "reject": still}
    return out


def direction(pair):
    return "better" if pair["b"] > pair["c"] else "worse" if pair["b"] < pair["c"] else "equal"


def quantiles(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return {"n": 0, "median": None, "p95": None, "mean": None, "max": None, "total": None}
    q = lambda p: xs[min(len(xs) - 1, int(p * len(xs)))]
    med = xs[len(xs) // 2] if len(xs) % 2 else (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2
    return {"n": len(xs), "median": med, "p95": q(0.95), "mean": sum(xs) / len(xs), "max": xs[-1], "total": sum(xs)}


def bootstrap_sums(rows, cols, n_boot, seed):
    """Item bootstrap: one index stream (random.Random(seed).randrange, as bootstrap_diff) shared
    by all columns; returns an (n_boot x len(cols)) array of column means."""
    import numpy as np
    n = len(rows)
    M = np.array([[float(r[c]) for c in cols] for r in rows]) if n else np.zeros((0, len(cols)))
    rng = random.Random(seed)
    out = np.zeros((n_boot, len(cols)))
    for b in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        out[b] = np.bincount(idx, minlength=n) @ M / n
    return out


def gap_closed(rows, methods, refs, n_boot, seed):
    """G = (acc - acc_MAJ) / (acc_REF - acc_MAJ); undefined if the denominator <= 0 (also per
    resample: undefined resamples are dropped from the percentile CI and counted)."""
    out = {}
    if not rows:
        return {m: {r: {"G": None, "undefined": True, "n": 0} for r in refs} for m in methods}
    cols = ["MAJ"] + refs + methods
    acc = {c: sum(r[c] for r in rows) / len(rows) for c in cols}
    bs = bootstrap_sums(rows, cols, n_boot, seed) if n_boot else None
    for m in methods:
        out[m] = {}
        for ref in refs:
            den = acc[ref] - acc["MAJ"]
            g = (acc[m] - acc["MAJ"]) / den if den > 0 else None
            e = {"G": g, "undefined": g is None, "n": len(rows), "acc": acc[m], "acc_MAJ": acc["MAJ"],
                 "acc_REF": acc[ref], "denominator": den}
            if bs is not None:
                d = bs[:, cols.index(ref)] - bs[:, 0]
                ok = d > 0
                gs = sorted(((bs[:, cols.index(m)] - bs[:, 0])[ok] / d[ok]).tolist())
                e["bootstrap"] = {"resamples": n_boot, "seed": seed, "unit": "item", "undefined_resamples": int((~ok).sum())}
                e["bootstrap_ci95"] = ([gs[int(0.025 * len(gs))], gs[min(len(gs) - 1, int(0.975 * len(gs)))]]
                                       if gs and g is not None else None)
            out[m][ref] = e
    return out


# ── loading ─────────────────────────────────────────────────────

def read_jsonl(p):
    if not p:
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def load_items(p):
    return {it["id"]: it for it in read_jsonl(p)}


def load_captures(p):
    out = {}
    for e in read_jsonl(p):
        rid = record_id(e["record"])
        if rid != e["capture_id"]:
            raise SystemExit(f"ABORT: capture {e['capture_id']} does not hash to its id ({rid})")
        out.setdefault(e["passage_key"], (e["capture_id"], e["record"]))
    return out


def load_checks(p):
    out = {}
    for e in read_jsonl(p):
        pk = PR.proposition_key(e["proposition_text"])
        if pk != e["proposition_key"]:
            raise SystemExit(f"ABORT: check {e['check_key']}: proposition_key mismatch")
        if PR.check_key(pk, e["passage_key"]) != e["check_key"]:
            raise SystemExit(f"ABORT: check {e['check_key']}: check_key mismatch")
        if e["check_key"] in out:
            raise SystemExit(f"ABORT: duplicate check {e['check_key']} (checks are de-duplicated)")
        out[e["check_key"]] = e
    return out


def load_judge(p, rename=None, out=None):
    """{(method, run): {id: row}}. A row with `dropped_agent` (leave-one-agent-out) is keyed
    (method + "/loao", run) and id "<item id>|<agent>". `rename` maps methods (the local judge's
    store writes J / RS rows; --judge-local reads them as J_local / RS_local)."""
    out = out if out is not None else defaultdict(dict)
    for e in read_jsonl(p):
        m = (rename or {}).get(e["method"], e["method"])
        iid = e["id"]
        if e.get("dropped_agent"):
            m, iid = m + "/loao", f"{e['id']}|{e['dropped_agent']}"
        key = (m, int(e.get("run", 0)))
        if iid in out[key]:
            raise SystemExit(f"ABORT: duplicate judge row {key} {iid}")
        out[key][iid] = dict(e, method=m)
    return out


# ── parsing and lowering ────────────────────────────────────────

def allowed_values(item):
    f = item["answer_format"]
    if f == "letter":
        return [o["letter"] for o in item["options"]]
    if f == "supported_refuted":
        return list(PR.BINARY_VALUES)
    return None


def flat_response(r):
    """One response in the evaluator's flat form. Accepts L3's `bran-v5-raw/1` response
    (answer_turn / retrieval.record / mode) and the flat form used by older fixtures."""
    if "answer_turn" in r or "harness_error" in r:
        at = r.get("answer_turn") or {}
        rt = r.get("retrieval") or {}
        return {"agent": r["agent"], "model": r.get("model"), "arrival_seq": r["arrival_seq"],
                "closed_book": r.get("mode") == "closed_book",
                "error": r.get("harness_error") or at.get("error") or rt.get("error"),
                "done_reason": (at.get("ollama_meta") or {}).get("done_reason"),
                "raw_response": at.get("raw_response") or "", "answer_json": None,
                "retrieval": rt.get("record") or {"results": []},
                "query": (r.get("query_turn") or {}).get("query_used")}
    return dict(r, retrieval=r.get("retrieval") or {"results": []})


def parse_answer(item, r):
    """(answer_dict | None, reason). A response is parsed iff its `answer` field is valid
    (the L3 rule: collect_v5.parse_answer); other schema violations are recorded and handled:
    confidence outside the enum -> "low"; citations not a list -> none; more than 3 -> the first
    3; non-string or duplicate labels dropped. Citation labels the agent was not shown are kept and
    become invalid_identifier (dead) captures (design §2.4 item 4)."""
    if r.get("error"):
        return None, "error"
    a = r.get("answer_json")
    if a is None:
        try:
            a = json.loads(r.get("raw_response") or "")
        except (ValueError, TypeError):
            return None, "truncated" if r.get("done_reason") == "length" else "not_json"
    if not isinstance(a, dict):
        return None, "not_json"
    ans = a.get("answer")
    if not isinstance(ans, str):
        return None, "answer_invalid"
    allowed = allowed_values(item)
    if allowed is not None:
        if ans not in allowed:
            return None, "answer_invalid"
        canonical = ans
    else:
        ans = " ".join(ans.split())
        if not ans or len(ans) > PR.MAX_ENTITY_CHARS:
            return None, "answer_invalid"
        canonical = C.canon(ans)
        if not canonical:
            return None, "answer_invalid"
    viol = []
    conf = a.get("confidence")
    if conf not in CONF:
        viol.append("confidence_bad")
        conf = "low"
    cites = a.get("citations")
    if not isinstance(cites, list):
        viol.append("citations_not_list")
        cites = []
    if any(not isinstance(x, str) for x in cites):
        viol.append("citation_not_string")
    cites = list(dict.fromkeys(x for x in cites if isinstance(x, str)))
    if len(cites) > 3:
        viol.append("too_many_citations")
        cites = cites[:3]
    if not isinstance(a.get("reasoning"), str):
        viol.append("reasoning_missing")
    return {"answer": ans, "canonical": canonical, "confidence": conf, "citations": cites,
            "violations": viol}, None


def grade_value(item, canonical, raw):
    return bool(AK.grade(item, canonical, raw))


def contribution_id(item_id, agent, obj):
    return hashlib.sha256(f"{item_id}|{agent}|answer|{obj}".encode()).hexdigest()[:16]


def response_view(item, r):
    r = flat_response(r)
    a, reason = parse_answer(item, r)
    retr = r["retrieval"]
    v = {"agent": r["agent"], "model": r.get("model"), "arrival_seq": r["arrival_seq"],
         "closed_book": bool(r.get("closed_book")), "error": r.get("error"), "done_reason": r.get("done_reason"),
         "parse_reason": reason, "parsed": None, "shown": [x["passage_key"] for x in retr.get("results") or []],
         "query": r.get("query"), "violations": a["violations"] if a else []}
    if a is None:
        return v
    prop = PR.render(item, a["answer"])
    keys = CC.citation_keys(retr, a["citations"])
    v.update(parsed=a["canonical"], answer=a["answer"], confidence=a["confidence"], prop=prop,
             cites=list(zip(a["citations"], keys)), correct=grade_value(item, a["canonical"], a["answer"]),
             _id=contribution_id(item["id"], r["agent"], a["canonical"]))
    return v


class Ctx:
    def __init__(self, args, captures, checks, judge, accepted=None):
        self.args, self.captures, self.checks, self.judge = args, captures, checks, judge
        self.accepted = sorted(set(accepted if accepted is not None else (args.accepted_checker or [])))
        self.counts = Counter()


def build_evidence(item, v, ctx, store):
    """Evidence items for one parsed answer; fills `store` with the referenced records.
    Returns (evidence list, per-citation audit list)."""
    ev, audit = [], []
    for lab, pk in v["cites"]:
        cap = ctx.captures.get(pk)
        if cap is None:
            ctx.counts["missing_capture"] += 1
            if ctx.args.strict:
                raise SystemExit(f"ABORT: no capture for {pk} ({item['id']} {v['agent']})")
            continue
        cid, rec = cap
        store["captures"][cid] = rec
        e = {"type": "CITATION", "source": rec["request_url"], "weight": 1.0, "reachable": True,
             "verification": "UNVERIFIED", "capture_ref": cid}
        a = {"label": lab, "passage_key": pk, "capture_id": cid, "outcome": rec["outcome"],
             "check": None, "support_label": None, "support_status": None, "score_q": None}
        if rec["outcome"] == "ok":
            ck = PR.check_key(v["prop"]["proposition_key"], pk)
            ent = ctx.checks.get(ck)
            a["check"] = ck
            if ent is None:
                ctx.counts["missing_check"] += 1
                if ctx.args.strict:
                    raise SystemExit(f"ABORT: no check {ck} for {item['id']} {v['agent']} {pk}")
            elif ent.get("capture_id") not in (None, cid):
                raise SystemExit(f"ABORT: check {ck} names capture {ent.get('capture_id')}, citation has {cid}")
            elif ent["status"] not in SEALABLE:
                ctx.counts["transient_check"] += 1
            else:
                st = SEALABLE[ent["status"]]
                ok = st == "ok"
                lab_m = PR.map_label(ent["label"], v["prop"]["label_map"]) if ok else None
                sup = {"format": "bran-support/1", "contribution_id": v["_id"],
                       "claim": {"subject": item["id"], "predicate": "answer", "object": v["parsed"],
                                 "polarity": "AFFIRM", "raw_text": v["prop"]["text"]},
                       "capture_id": cid, "spans": ent.get("spans") or [],
                       "span_selector": ent.get("span_selector") or DEFAULT_SPAN_SELECTOR,
                       "checker": ent["checker"], "status": st, "label": lab_m,
                       "score_q": ent["score_q"] if ok else None,
                       "raw_output_sha256": ent.get("raw_output_sha256")}
                sid = record_id(sup)
                store["support"][sid] = sup
                e["support_ref"] = sid
                accepted = ent["checker"]["checker_id"] in ctx.accepted
                a.update(support_label=lab_m, support_status=st, score_q=sup["score_q"], accepted=accepted)
                ctx.counts["support_records"] += 1
        ev.append(e)
        audit.append(a)
    return ev, audit


def lower(item, v):
    return {"id": v["_id"], "agent_id": v["agent"], "agent_name": v["agent"], "kind": "ASSERTION",
            "canonical_form": {"subject": item["id"], "predicate": "answer", "object": v["parsed"],
                               "polarity": "AFFIRM"},
            "confidence": CONF[v["confidence"]], "lowering_confidence": "HIGH",
            "evidence": v["evidence"], "raw_text": v["prop"]["text"], "seq": v["arrival_seq"] * 1000}


# ── policies ────────────────────────────────────────────────────

def parse_config(name):
    """(mode, nei, gated) of a grid name: `<mode>/nei<f>` or `<mode>/nei<f>/gated`."""
    if name not in FULL_GRID:
        raise SystemExit(f"unknown BE configuration {name!r}; grid: {FULL_GRID}")
    gated = name.endswith(GATED)
    mode, _, nei = name[:-len(GATED)].partition("/nei") if gated else name.partition("/nei")
    return mode, float(nei), gated


def changed_fields(name):
    mode, nei, gated = parse_config(name)
    return int(mode != "member") + int(nei != 0.5) + int(gated)


def evidence_policy(accepted, nei, gated=False):
    p = {"format": "bran-evidence-policy/1", "unchecked_factor": UNCHECKED_FACTOR,
         "accepted_checkers": list(accepted),
         "support_factor": {"supports": 1.0, "not_enough_info": nei, "refutes": 0.0}}
    if gated:
        p["overturn_gate"] = "verified"
    return p


def policy_for(method, objects, accepted, config=None):
    """method: B0 | BE | EO (config = BE grid name for BE and EO)."""
    p = copy.deepcopy(BASE_POLICY)
    p["values"]["incompatible_values"] = {"answer": {"__all_objects__": sorted({norm_obj(o) for o in objects})}}
    p.update(copy.deepcopy(M3_OVERLAY))
    if method in ("BE", "EO"):
        mode, nei, gated = parse_config(config)
        p["evidence"] = evidence_policy(accepted, nei, gated)
        if mode != "member":
            p["candidate_mode"] = {"mode": "value", "aggregate": mode.split(":")[1]}
        if method == "EO":
            p["weights"] = [1.0, 0.0, 0.0, 0.0, 0.0]
            p["deadband_threshold"] = 0
    return p


# ── Rust ────────────────────────────────────────────────────────

def run_rust(binary, inp, fin):
    fin.parent.mkdir(parents=True, exist_ok=True)
    with open(fin, "w") as f:
        json.dump(inp, f, indent=1, sort_keys=True)
    t0 = time.perf_counter()
    r = subprocess.run([binary, "--reduce", str(fin), "--no-color"], capture_output=True)
    wall = time.perf_counter() - t0
    if r.returncode != 0:
        raise RuntimeError(f"bran --reduce failed on {fin}: {r.stderr.decode(errors='replace')}")
    return json.loads(r.stdout), r.stdout, wall


def rust_select(out):
    sel = [s for s in out["selections"] if s["type"] == "CONTRADICTION"]
    if len(sel) > 1:
        raise RuntimeError("more than one contradiction slot for one item")
    return sel[0] if sel else None


# ── Python mirror of one single-slot reduction (ASSERTION/AFFIRM/HIGH only) ──

TW = {"TOOL_RESULT": 1.0, "EMPIRICAL": 0.9, "CITATION": 0.8, "AUTHORITY": 0.5, "REASONING": 0.3}
VQ = {"UNVERIFIED": 0.40, "REACHABILITY_CHECKED": 0.70, "CONTENT_HASHED": 0.85, "CROSS_REFERENCED": 0.95,
      "STALE": 0.20}
DEAD = {"not_found", "dns_nxdomain", "invalid_identifier", "blocked_ssrf"}
EV_DEFAULT = {"outcome_quality": {"reachable_text": 0.85, "reachable": 0.70, "dead": 0.20},
              "outcome_reach": {"reachable_text": 0.75, "reachable": 0.75, "dead": 0.45},
              "support_factor": {"supports": 1.0, "not_enough_info": 0.5, "refutes": 0.0},
              "unchecked_factor": 1.0, "use_support_score": False, "xref_requires_support": True,
              "legacy_source_xref": False, "accepted_checkers": [], "overturn_gate": "none"}


def q_round(x):
    """Rust f64::round (half away from zero) of x*10000."""
    y = x * 10000.0
    return int(math.floor(y + 0.5)) if y >= 0 else -int(math.floor(-y + 0.5))


def _class(outcome):
    if outcome == "ok":
        return "reachable_text"
    if outcome == "ok_no_text":
        return "reachable"
    return "dead" if outcome in DEAD else "transient"


def _legacy_reach(e):
    if e["type"] in ("CITATION", "TOOL_RESULT", "EMPIRICAL"):
        return 0.75 if e.get("reachable", True) else 0.45
    return {"AUTHORITY": 0.5, "REASONING": 0.3}[e["type"]]


def _source_quality(e):
    return 1.0 if e["type"] in ("TOOL_RESULT", "REASONING") else VQ[e.get("verification", "UNVERIFIED")]


def _factors(e, c, store, pol):
    """(q, r, s, xref_key, eligible, label) as bran/src/evidence.rs `factors`."""
    cap = store["captures"].get(e.get("capture_ref")) if e.get("capture_ref") else None
    if cap is None:
        key = ("src:" + e["source"].lower()) if pol["legacy_source_xref"] else None
        return _source_quality(e), _legacy_reach(e), pol["unchecked_factor"], key, key is not None, None
    k = _class(cap["outcome"])
    if e["type"] in ("TOOL_RESULT", "REASONING"):
        q = 1.0
    else:
        q = pol["outcome_quality"][k] if k != "transient" else VQ[e.get("verification", "UNVERIFIED")]
    if e["type"] in ("CITATION", "TOOL_RESULT", "EMPIRICAL"):
        r = pol["outcome_reach"][k] if k != "transient" else _legacy_reach(e)
    else:
        r = _legacy_reach(e)
    label = None
    sup = store["support"].get(e.get("support_ref")) if e.get("support_ref") else None
    if (sup and sup["status"] == "ok" and sup["contribution_id"] == c["id"]
            and e.get("capture_ref") == sup["capture_id"] and sup["checker"]["checker_id"] in pol["accepted_checkers"]):
        label = (sup["label"], sup["score_q"])
    if label:
        f = pol["support_factor"][label[0]]
        s = f * label[1] / 10000.0 if pol["use_support_score"] else f
    else:
        s = pol["unchecked_factor"]
    key = None
    if k in ("reachable_text", "reachable") and cap.get("canonical_url"):
        u = cap["canonical_url"]
        key = ("corpus:" + u[len("corpus://"):]) if cap["identifier_kind"] == "corpus" else ("url:" + u)
    elig = key is not None and (not pol["xref_requires_support"] or (label is not None and label[0] == "supports"))
    return q, r, s, key, elig, label


def _mult(n):
    return 1.2 if n >= 3 else 1.1 if n >= 2 else 0.9


def mirror(inp):
    """Selection of the single CONTRADICTION slot, or None if < 2 distinct values."""
    pol = inp["policy"]
    contribs = sorted(inp["contributions"], key=lambda c: (c["seq"], c["id"]))   # canonical order
    if len({norm_obj(c["canonical_form"]["object"]) for c in contribs}) < 2:
        return None
    store = inp.get("evidence_store") or {"captures": {}, "support": {}}
    epol = None
    if "evidence" in pol:
        epol = copy.deepcopy(EV_DEFAULT)
        epol.update(copy.deepcopy(pol["evidence"]))
    w, db = pol["weights"], pol["deadband_threshold"]
    mask, eps = pol.get("schulze_dims", 31), pol["schulze_dim_epsilon"]
    citers = defaultdict(set)
    for c in contribs:
        for e in c["evidence"]:
            if epol:
                _, _, _, key, elig, _ = _factors(e, c, store, epol)
                if elig:
                    citers[key].add(c["agent_id"])
            else:
                citers[e["source"].lower()].add(c["agent_id"])
    n, denom = len(contribs), max(len(contribs) - 1, 1)
    dims, fin, sq = {}, {}, {}
    for rank, c in enumerate(contribs):
        ev = 0.0
        for e in c["evidence"]:
            if epol:
                q, r, s, key, elig, _ = _factors(e, c, store, epol)
                base = e["weight"] * TW[e["type"]] * q * r * s
                ev += base * (_mult(len(citers.get(key, ())) or 1) if elig else 0.9)
            else:
                base = e["weight"] * TW[e["type"]] * _source_quality(e) * _legacy_reach(e)
                ev += base * _mult(len(citers.get(e["source"].lower(), ())) or 1)
        ev = min(max(ev, 0.0), 1.0) if c["evidence"] else 0.0
        conf = min(c["confidence"] * inp["calibration"].get(c["agent_id"], 0.5), 1.0)
        rec = rank / denom
        raw = w[0] * ev + w[1] * conf + w[2] * 1.0 + w[3] * rec + w[4] * 1.0
        fin[c["id"]] = raw * 1.0
        sq[c["id"]] = q_round(fin[c["id"]])
        dims[c["id"]] = [ev, conf, 1.0, rec, 1.0]
    ids = [c["id"] for c in contribs]
    by_id = {c["id"]: c for c in contribs}
    sc = {"sq": sq, "fin": fin, "dims": dims, "by_id": by_id, "w": w, "db": db, "mask": mask, "eps": eps,
          "cm": pol.get("candidate_mode", {"mode": "member"})}
    if not (epol and epol.get("overturn_gate", "none") == "verified"):
        winner, inb = _select(ids, sc)
        return {"members": ids, "winner": winner, "scores_q": sq, "in_deadband": inb, "gate": None}
    # verified-overturn gate (bran/src/gate.rs, v3/GATE_SPEC.md)
    groups = defaultdict(list)
    for i in ids:
        groups[norm_obj(by_id[i]["canonical_form"]["object"])].append(i)   # v5: AFFIRM only
    nag = {k: len({by_id[i]["agent_id"] for i in m}) for k, m in groups.items()}
    top = max(nag.values())
    wit = sorted(i for i in ids if any(_factors(e, by_id[i], store, epol)[5] is not None
                                       and _factors(e, by_id[i], store, epol)[5][0] == "supports"
                                       for e in by_id[i]["evidence"]))
    plural = [i for i in ids if nag[norm_obj(by_id[i]["canonical_form"]["object"])] == top]
    verified = [i for k, m in groups.items() if any(i in wit for i in m) for i in m]
    d, d_inb = _select(plural, sc)
    if verified:
        winner, inb = _select(verified, sc)
        stage, cands = "verified", verified
    else:
        winner, inb, stage, cands = d, d_inb, "plurality", plural
    obj = lambda i: norm_obj(by_id[i]["canonical_form"]["object"])
    gate = {"stage": stage, "default_winner": d, "plurality_agents": top, "candidates": sorted(cands),
            "witnesses": wit, "overturned": obj(winner) != obj(d)}
    return {"members": ids, "winner": winner, "scores_q": sq, "in_deadband": inb, "gate": gate}


def _select(cand, sc):
    """Ordinary P5 selection (order-free policy: tiebreak_order id) over the members `cand` only."""
    sq, fin, dims, by_id, w = sc["sq"], sc["fin"], sc["dims"], sc["by_id"], sc["w"]
    db, mask, eps, cm = sc["db"], sc["mask"], sc["eps"], sc["cm"]
    if cm["mode"] == "member":
        best = sorted(cand, key=lambda i: (-sq[i], i))[0]
        top = sorted((sq[i] for i in cand), reverse=True)
        inb = len(cand) >= 2 and top[0] - top[1] < db
        if inb:
            dc = sorted(i for i in cand if top[0] - sq[i] < db)
            qd = {i: [q_round(x) for x in dims[i]] for i in dc}
            best = schulze_masked(dc, qd, mask, eps)
        return best, inb
    agg = cm.get("aggregate", "max")
    groups = defaultdict(list)
    for i in cand:
        groups[norm_obj(by_id[i]["canonical_form"]["object"])].append(i)
    vals = []
    for mem in groups.values():
        rep = sorted(mem, key=lambda i: (-sq[i], i))[0]
        if agg == "max":
            vd, vs = dims[rep], fin[rep]
        else:
            per_agent = {}
            for i in mem:
                a = by_id[i]["agent_id"]
                per_agent[a] = max(per_agent.get(a, 0.0), dims[i][0])
            ev = min(max(sum(per_agent[a] for a in sorted(per_agent)), 0.0), 1.0)
            k = len(mem)
            mean = [sum(dims[i][j] for i in mem) / k for j in (1, 2, 3, 4)]
            vd = [ev] + mean
            raw = w[0] * vd[0] + w[1] * vd[1] + w[2] * vd[2] + w[3] * vd[3] + w[4] * vd[4]
            vs = raw * (sum(1.0 for _ in mem) / k)
        vals.append({"rep": rep, "dims": [q_round(x) for x in vd], "score": q_round(vs)})
    vals.sort(key=lambda v: v["rep"])
    bi = 0
    for i, v in enumerate(vals):
        if v["score"] > vals[bi]["score"]:
            bi = i
    winner = vals[bi]["rep"]
    ss = sorted((v["score"] for v in vals), reverse=True)
    inb = len(vals) >= 2 and ss[0] - ss[1] < db
    if inb:
        top = vals[bi]["score"]
        cands = [v for v in vals if top - v["score"] < db]
        reps = [v["rep"] for v in cands]
        winner = schulze_masked(reps, {v["rep"]: v["dims"] for v in cands}, mask, eps)
    return winner, inb


def schulze_masked(members, dims, mask, eps):
    """evaluate_v4.schulze_masked (verified against the binary in v4)."""
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


def check_mirror(sel, mir, where):
    if (sel is None) != (mir is None) or (sel is not None and (
            sel["winner"] != mir["winner"] or sel["in_deadband"] != mir["in_deadband"]
            or {k: int(v) for k, v in sel["scores_q"].items()} != mir["scores_q"]
            or sorted(sel["members"]) != sorted(mir["members"])
            or sel.get("gate") != mir["gate"])):
        raise SystemExit(f"ABORT: Python mirror != binary on {where}: {sel} vs {mir}")


# ── per item ────────────────────────────────────────────────────

def prepare_item(item, raw, ctx):
    views = [response_view(item, r) for r in sorted(raw["responses"], key=lambda r: r["arrival_seq"])]
    parsed = [v for v in views if v["parsed"] is not None]
    if len({v["agent"] for v in parsed}) != len(parsed):
        raise SystemExit(f"ABORT: {item['id']}: more than one response per agent")
    store = {"captures": {}, "support": {}}
    for v in parsed:
        v["evidence"], v["audit"] = build_evidence(item, v, ctx, store)
    contribs = [lower(item, v) for v in parsed]
    src = item["source"]["key"]
    n_correct = sum(v["correct"] for v in parsed)
    row = {"id": item["id"], "source": src, "stratum": item["source"].get("stratum", ""),
           "n_responses": len(views), "n_parsed": len(parsed), "n_correct": n_correct,
           "eligible": int(len(parsed) >= 2), "decisive": int(len(parsed) >= 2 and 0 < n_correct < len(parsed)),
           "n_distinct": len({v["parsed"] for v in parsed})}
    return {"item": item, "views": views, "parsed": parsed, "contribs": contribs, "store": store, "row": row,
            "by_id": {v["_id"]: v for v in parsed}}


def object_correct(rec, obj):
    holders = sorted((v for v in rec["parsed"] if v["parsed"] == obj), key=lambda v: v["_id"])
    return int(grade_value(rec["item"], obj, holders[0]["answer"])), len({v["correct"] for v in holders}) > 1


def reduce_method(rec, method, config, ctx, tag):
    item = rec["item"]
    inp = {"intent": item["question"], "criteria": [], "calibration": {c["agent_id"]: CALIBRATION for c in rec["contribs"]},
           "policy": policy_for(method, [c["canonical_form"]["object"] for c in rec["contribs"]], ctx.accepted, config),
           "contributions": rec["contribs"]}
    if rec["store"]["captures"]:
        inp["evidence_store"] = rec["store"]
    out, raw, wall = run_rust(ctx.args.bin, inp, ctx.rdir / item["id"] / f"{tag}.in.json")
    with open(ctx.rdir / item["id"] / f"{tag}.out.json", "wb") as f:
        f.write(raw)
    sel = rust_select(out)
    check_mirror(sel, mirror(inp), f"{item['id']} {tag}")
    ctx.counts["mirror_checked"] += 1
    if sel is None:
        obj = rec["contribs"][0]["canonical_form"]["object"]
        ok, _ = object_correct(rec, obj)
        winner = None
    else:
        winner = sel["winner"]
        obj, ok = rec["by_id"][winner]["parsed"], int(rec["by_id"][winner]["correct"])
    return {"correct": ok, "obj": obj, "winner": winner, "sel": sel, "policy_hash": out["policy_hash"],
            "root_hash": out["root_hash"], "inp": inp, "stdout": raw, "wall_s": wall, "fin": ctx.rdir / item["id"] / f"{tag}.in.json"}


def supports_effective(v, accepted):
    return any(a.get("support_label") == "supports" and a.get("support_status") == "ok" and a.get("accepted")
               for a in v["audit"])


def _plurality(values, seed):
    """Plurality over a list of canonical values; ties by random.Random(seed).choice(sorted ties)."""
    cnt = Counter(values)
    top = max(cnt.values())
    tied = sorted(o for o, k in cnt.items() if k == top)
    return (tied[0] if len(tied) == 1 else random.Random(seed).choice(tied)), tied


def vv_value(rec, accepted, maj):
    """VV: plurality among answers with >= 1 accepted `supports` citation, else MAJ."""
    ver = [v for v in rec["parsed"] if supports_effective(v, accepted)]
    if not ver:
        return maj, 1
    return _plurality([v["parsed"] for v in ver], "v5-vv:" + rec["item"]["id"])[0], 0


def _judge_select(rec, ctx, row, method, cnt, maj):
    """J-style judge (picks a proposed value): null -> MAJ (counted); `<m>_nullwrong` scores it wrong."""
    j = ctx.judge.get((method, 0), {}).get(rec["item"]["id"])
    row[method + "_has_row"] = int(j is not None)
    jobj = judge_value(rec["item"], j, cnt) if j else None
    if jobj is None:
        row[method], row[method + "_obj"], row[method + "_fallback"] = row["MAJ"], maj, 1
        row[method + "_nullwrong"] = 0
    else:
        row[method], _ = object_correct(rec, jobj)
        row[method + "_obj"], row[method + "_fallback"] = jobj, 0
        row[method + "_nullwrong"] = row[method]


def _reader_answer(rec, ctx, row, method):
    """RS / CB-S: a free answer graded by G-AK directly; null -> wrong."""
    item = rec["item"]
    e = ctx.judge.get((method, 0), {}).get(item["id"])
    row[method + "_has_row"] = int(e is not None)
    if e and e.get("status", "ok") in ("ok", "forced") and e.get("selected"):
        s = e["selected"]
        cv = canonical_of(item, s)
        row[method] = int(cv is not None and grade_value(item, cv, s))
        row[method + "_obj"], row[method + "_missing"] = cv, 0
    else:
        row[method], row[method + "_obj"], row[method + "_missing"] = 0, None, 1


def python_methods(rec, ctx, best_agent):
    item, parsed, row = rec["item"], rec["parsed"], rec["row"]
    iid = item["id"]
    cnt = Counter(v["parsed"] for v in parsed)
    maj, tied = _plurality([v["parsed"] for v in parsed], "v5-majority:" + iid)
    top = cnt[tied[0]]
    row["MAJ"], mx = object_correct(rec, maj)
    row["MAJ_obj"], row["majority_tied"], row["majority_top_count"] = maj, int(len(tied) > 1), top
    row["MAJ_expected"] = sum(object_correct(rec, o)[0] for o in tied) / len(tied)
    row["mixed_objects"] = int(mx)
    # sensitivity (§10): MAJ with earliest-arrival ties
    first = {}
    for v in parsed:
        first.setdefault(v["parsed"], v["arrival_seq"])
    early = min(tied, key=lambda o: (first[o], o))
    row["MAJ_early"], _ = object_correct(rec, early)
    row["MAJ_early_obj"] = early
    vv, fb = vv_value(rec, ctx.accepted, maj)
    row["VV"], _ = object_correct(rec, vv)
    row["VV_obj"], row["VV_fallback"] = vv, fb
    # CV: plurality among answers citing >= 1 shown passage (any label, unverified), else MAJ
    citing = [v for v in parsed if any(k in v["shown"] for _, k in v["cites"])]
    if citing:
        cv = _plurality([v["parsed"] for v in citing], "v5-cv:" + iid)[0]
        row["CV_fallback"] = 0
    else:
        cv, row["CV_fallback"] = maj, 1
    row["CV"], _ = object_correct(rec, cv)
    row["CV_obj"] = cv
    # CONF: per value, the sum of members' confidence weights; argmax; ties seeded
    w = defaultdict(float)
    for v in parsed:
        w[v["parsed"]] += CONF[v["confidence"]]
    wq = {o: q_round(x) for o, x in w.items()}          # exact ties on the 10,000 scale
    wt = sorted(o for o in wq if wq[o] == max(wq.values()))
    conf = wt[0] if len(wt) == 1 else random.Random("v5-conf:" + iid).choice(wt)
    row["CONF"], _ = object_correct(rec, conf)
    row["CONF_obj"] = conf
    own = [v for v in parsed if v["agent"] == best_agent]
    row["BEST"] = int(own[0]["correct"]) if own else row["MAJ"]
    row["BEST_fallback"] = int(not own)
    row["ORC"] = int(row["n_correct"] > 0)
    _judge_select(rec, ctx, row, "J", cnt, maj)
    _judge_select(rec, ctx, row, "J_local", cnt, maj)
    _reader_answer(rec, ctx, row, "RS")
    _reader_answer(rec, ctx, row, "CB-S")


def canonical_of(item, s):
    allowed = allowed_values(item)
    if allowed is not None:
        s2 = s.strip().upper()
        return s2 if s2 in allowed else None
    c = C.canon(" ".join(s.split()))
    return c or None


def judge_value(item, j, cnt):
    if j.get("status", "ok") not in ("ok", "forced") or not j.get("selected"):
        return None
    cv = canonical_of(item, j["selected"])
    return cv if cv in cnt else None


def separation(rec, sel):
    """S4 under BE: min correct member score - max incorrect member score (10,000 scale)."""
    if sel is None:
        return None
    corr = [sel["scores_q"][i] for i in sel["members"] if rec["by_id"][i]["correct"]]
    inc = [sel["scores_q"][i] for i in sel["members"] if not rec["by_id"][i]["correct"]]
    if not corr or not inc:
        return None
    return min(corr) - max(inc)


# ── dev gate ────────────────────────────────────────────────────

def gold_value(item):
    """Gold answer as a proposable value (letter, SUPPORTED/REFUTED, or the PopQA object string)."""
    return item["gold"]["answer"]


def evidence_availability(recs, ctx):
    """Share of decisive items where some agent's shown top-k holds a passage labelled
    `supports` (mapped, accepted checker, status ok) for the gold value. Diagnostic only."""
    out = defaultdict(lambda: Counter())
    for rec in recs:
        if not rec["row"]["decisive"]:
            continue
        item = rec["item"]
        src = item["source"]["key"]
        try:
            prop = PR.render(item, gold_value(item))
        except PR.PropositionError:
            out[src]["unrenderable"] += 1
            continue
        shown = sorted({pk for v in rec["views"] for pk in v["shown"]})
        hit = False
        for pk in shown:
            out[src]["pairs"] += 1
            ent = ctx.checks.get(PR.check_key(prop["proposition_key"], pk))
            if ent is None:
                continue
            out[src]["pairs_checked"] += 1
            if (ent["status"] == "ok" and ent["checker"]["checker_id"] in ctx.accepted
                    and PR.map_label(ent["label"], prop["label_map"]) == "supports"):
                hit = True
        out[src]["decisive"] += 1
        out[src]["available"] += int(hit)
    res = {}
    for src, c in sorted(out.items()):
        res[src] = {"decisive": c["decisive"], "available": c["available"],
                    "availability": c["available"] / c["decisive"] if c["decisive"] else None,
                    "gold_passage_pairs": c["pairs"], "pairs_checked": c["pairs_checked"],
                    "check_coverage": c["pairs_checked"] / c["pairs"] if c["pairs"] else None,
                    "lower_bound": c["pairs_checked"] < c["pairs"]}
    return res


def per_agent(recs):
    out = {}
    agents = sorted({v["agent"] for r in recs for v in r["views"]})
    for a in agents:
        vs = [v for r in recs for v in r["views"] if v["agent"] == a]
        n = len(vs)
        fails = [v for v in vs if v["parsed"] is None]
        out[a] = {"responses": n, "parse_failures": len(fails),
                  "parse_failure_rate": len(fails) / n if n else None,
                  "reasons": dict(Counter(v["parse_reason"] for v in fails)),
                  "violations": dict(Counter(x for v in vs for x in v["violations"])),
                  "invalid_citations": sum(1 for v in vs for _, k in v.get("cites", []) if k not in v["shown"]),
                  "truncated_length": sum(1 for v in vs if v["done_reason"] == "length"),
                  "closed_book": sum(1 for v in vs if v["closed_book"]),
                  "correct": sum(1 for v in vs if v.get("correct")),
                  "accuracy_all_items": sum(1 for v in vs if v.get("correct")) / n if n else None,
                  "citing_answers": sum(1 for v in vs if v.get("cites")),
                  "parsed_answers": n - len(fails)}
    return out


def dev_gate(recs, rows, dec, pa, ctx):
    n = len(rows)
    y = len(dec) / n if n else 0.0
    m = sum(1 for r in dec if not r["MAJ"]) / len(dec) if dec else 0.0
    m_exp = sum(1 - r["MAJ_expected"] for r in dec) / len(dec) if dec else 0.0
    ea = evidence_availability(recs, ctx)
    worst_pf = max((a["parse_failure_rate"] or 0.0) for a in pa.values()) if pa else 0.0
    checks = {
        "yield": {"value": y, "threshold": GATE["yield"], "pass": y >= GATE["yield"], "if_fail": "mixed-fleet arm (§3.2)"},
        "majority_wrong_share": {"value": m, "value_expected_tiebreak": m_exp, "threshold": GATE["m"],
                                 "pass": m >= GATE["m"], "if_fail": "mixed-fleet arm (§3.2)"},
        "evidence_availability": {"per_source": ea, "threshold": GATE["evidence_availability"],
                                  "pass": all((v["availability"] or 0.0) >= GATE["evidence_availability"] for v in ea.values()),
                                  "failing_sources": sorted(s for s, v in ea.items()
                                                            if (v["availability"] or 0.0) < GATE["evidence_availability"]),
                                  "if_fail": "§2.2 TQA switch (TruthfulQA quota -> PopQA and FEVER)"},
        "parse_failure": {"per_agent": {a: v["parse_failure_rate"] for a, v in pa.items()}, "worst": worst_pf,
                          "threshold": GATE["parse_failure"], "pass": worst_pf < GATE["parse_failure"],
                          "if_fail": "one schema fix"},
    }
    checks["all_pass"] = all(c["pass"] for k, c in checks.items() if isinstance(c, dict))
    return checks


# ── main ────────────────────────────────────────────────────────

def template_sha(method, cfg, accepted):
    """policy_template_sha256: the method's policy with the per-item `values` block nulled."""
    p = policy_for(method, [], accepted, cfg)
    p["values"] = None
    return sha256_json(p)


def analysis_set(item, strict):
    """P (primary) or T (TruthfulQA no-coverage stratum), from the item `tier` (prereg §6.3). Items
    without those tiers (dev, older fixtures): T = TruthfulQA, P = the rest. strict (conf): the
    tier must be primary or tqa_stratum."""
    tier, src = item.get("tier"), item["source"]["key"]
    if tier == "primary":
        if src == "truthfulqa":
            raise SystemExit(f"ABORT: {item['id']}: tier primary on a TruthfulQA item (switch build, prereg §6.3)")
        return "P"
    if tier == "tqa_stratum":
        if src != "truthfulqa":
            raise SystemExit(f"ABORT: {item['id']}: tier tqa_stratum on a {src} item")
        return "T"
    if strict:
        raise SystemExit(f"ABORT: {item['id']}: conf item tier {tier!r} is neither primary nor tqa_stratum")
    return "T" if src == "truthfulqa" else "P"


def parse_rate(s):
    """`a/b` or a float -> {"rate", "num", "den"}."""
    if s is None:
        return None
    if isinstance(s, tuple):
        return {"rate": s[0] / s[1], "num": s[0], "den": s[1]}
    if "/" in s:
        a, b = s.split("/")
        return {"rate": int(a) / int(b), "num": int(a), "den": int(b)}
    return {"rate": float(s), "num": None, "den": None}


def provenance(args, ctx, ctx_local=None, extra=None):
    prov = {"format": FORMAT, "binary": args.bin, "binary_sha256": sha256_file(args.bin),
            "evaluate_v5_py_sha256": sha256_file(__file__),
            "propositions": PR.renderer_identity(),
            "propositions_py_sha256": sha256_file(PR.__file__),
            "corpus_capture_py_sha256": sha256_file(CC.__file__),
            "answer_key_py_sha256": sha256_file(AK.__file__), "canon": AK.canon_provenance(),
            "accepted_checkers": ctx.accepted, "grid": GRID,
            "dev_informed_grid": DEV_INFORMED, "base_policy": BASE_POLICY, "m3_overlay": M3_OVERLAY,
            "local_accepted_checkers": ctx_local.accepted if ctx_local else None,
            "judge_ids_seen": {f"{m}#{r}": sorted({e.get("judge_id") for e in rows.values() if e.get("judge_id")})
                               for (m, r), rows in sorted(ctx.judge.items())},
            "inputs": {}}
    for k in ("items", "captures", "checks", "judge", "local_checks", "judge_local"):
        p = getattr(args, k, None)
        prov["inputs"][k] = {"path": p, "sha256": sha256_file(p)} if p else None
    prov.update(extra or {})
    return prov


def replay_same(binary, res):
    r2 = subprocess.run([binary, "--reduce", str(res["fin"]), "--no-color"], capture_output=True)
    return r2.returncode == 0 and r2.stdout == res["stdout"]


def leave_one_out(rec, cfg, ctx, full_obj):
    """BE-G re-decided once per dropped agent from the sealed labels (0 model calls)."""
    out = []
    for a in [v["agent"] for v in rec["parsed"]]:
        contribs = [c for c in rec["contribs"] if c["agent_id"] != a]
        caps = {e["capture_ref"] for c in contribs for e in c["evidence"] if e.get("capture_ref")}
        sups = {e["support_ref"] for c in contribs for e in c["evidence"] if e.get("support_ref")}
        sub = dict(rec, contribs=contribs,
                   store={"captures": {k: v for k, v in rec["store"]["captures"].items() if k in caps},
                          "support": {k: v for k, v in rec["store"]["support"].items() if k in sups}})
        r = reduce_method(sub, "BE", cfg, ctx, "LOAO_" + a)
        out.append({"id": rec["item"]["id"], "dropped_agent": a, "obj": r["obj"], "changed": int(r["obj"] != full_obj),
                    "wall_s": r["wall_s"]})
    return out


def f_and_pairs(rec, accepted):
    """F: some incorrect value carries an accepted `supports` label. F-hat pairs: the distinct
    checked (incorrect value's proposition, cited passage) pairs (accepted checker, status ok)."""
    f = any(supports_effective(v, accepted) and not v["correct"] for v in rec["parsed"])
    pairs = {a["check"] for v in rec["parsed"] if not v["correct"] for a in v["audit"]
             if a.get("check") and a.get("support_status") == "ok" and a.get("accepted")}
    return int(f), len(pairs)


def gated_row(rec, row, res, prefix, dprefix):
    gt = (res["sel"] or {}).get("gate")
    row[prefix], row[prefix + "_obj"] = res["correct"], res["obj"]
    row[prefix + "_stage"] = gt["stage"] if gt else "no_slot"
    row[prefix + "_overturned"] = int(bool(gt and gt["overturned"]))
    if gt:
        row[dprefix], row[dprefix + "_obj"] = int(rec["by_id"][gt["default_winner"]]["correct"]), \
            rec["by_id"][gt["default_winner"]]["parsed"]
    else:
        row[dprefix], row[dprefix + "_obj"] = row["MAJ"], row["MAJ_obj"]


def main(argv=None):
    ap = argparse.ArgumentParser(description="eval v5 analysis")
    ap.add_argument("--split", choices=["dev", "conf"])
    ap.add_argument("--bin")
    ap.add_argument("--items")
    ap.add_argument("--raw-dir")
    ap.add_argument("--captures")
    ap.add_argument("--checks")
    ap.add_argument("--judge")
    ap.add_argument("--out")
    ap.add_argument("--accepted-checker", action="append")
    ap.add_argument("--be-config", help="frozen ungated BE configuration (conf; prereg: member/nei0.1)")
    ap.add_argument("--be-g-config", help="frozen gated BE-G configuration (conf; prereg: member/nei0.5/gated)")
    ap.add_argument("--best-model", help="agent id for BEST (required for conf; fixed on dev)")
    ap.add_argument("--local-checks", help="checks JSONL of the local checker (BE-G-L, VV-L)")
    ap.add_argument("--local-accepted-checker", help="the local checker_id accepted for BE-G-L")
    ap.add_argument("--local-arm", choices=["confirmatory", "exploratory"],
                    help="H2 status (prereg §2.3); default exploratory when --local-checks is given")
    ap.add_argument("--judge-local", help="local judge rows (tools/judge/local_judge.py rows): J -> J_local")
    ap.add_argument("--local-judge-agent", default=PREREG_BEST, help="the agent J_local's model also plays")
    ap.add_argument("--expect-template", action="append", default=[], metavar="METHOD=SHA256",
                    help="assert a policy_template_sha256 (e.g. BE-G-L=<sha>); always checked")
    ap.add_argument("--expect-judge-id", action="append", default=[], metavar="METHOD=ID",
                    help="assert every row of METHOD carries this judge_id (e.g. CB-S=<id>)")
    ap.add_argument("--fhat-rate", help="F-hat false-support rate a/b (default: the prereg rate of the accepted checker)")
    ap.add_argument("--local-fhat-rate", help="F-hat rate for the local checker")
    ap.add_argument("--no-loao", action="store_true", help="skip the BE-G leave-one-agent-out replay")
    ap.add_argument("--bootstrap", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--strict", action="store_true", help="abort on a missing capture or check")
    ap.add_argument("--synthetic-test", action="store_true",
                    help="run on SYNTHETIC records only (raw dir must contain a SYNTHETIC marker file)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    for k in ("split", "bin", "items", "raw_dir", "out"):
        if not getattr(args, k):
            ap.error(f"--{k.replace('_', '-')} is required")
    raw_dir = Path(args.raw_dir).resolve()
    if "v4/results/conf" in str(raw_dir).replace("\\", "/"):
        raise SystemExit("refused: v4 confirmatory data are blinded")
    if args.synthetic_test and not (raw_dir / "SYNTHETIC").exists():
        raise SystemExit("refused: --synthetic-test needs --raw-dir with a SYNTHETIC marker file")
    if (raw_dir / "SYNTHETIC").exists() and not args.synthetic_test:
        raise SystemExit("refused: raw dir is SYNTHETIC; pass --synthetic-test")
    expect_tpl = dict(e.split("=", 1) for e in args.expect_template)
    expect_jid = dict(e.split("=", 1) for e in args.expect_judge_id)
    local_arm = args.local_arm or ("exploratory" if args.local_checks else None)
    if args.local_checks and not args.local_accepted_checker:
        raise SystemExit("ABORT: --local-checks given without --local-accepted-checker")
    if local_arm == "confirmatory" and not (args.local_checks and args.judge_local):
        raise SystemExit("ABORT: --local-arm confirmatory needs --local-checks and --judge-local")
    if args.split == "conf":
        if not (args.be_config and args.be_g_config and args.best_model):
            raise SystemExit("ABORT: conf needs --be-g-config, --be-config and --best-model (all fixed on dev)")
        if not args.synthetic_test:
            fz = HERE / "FREEZE.json"
            frozen = jload(fz).get("sha256", {}) if fz.exists() else {}
            rel = lambda p: str(Path(p).resolve().relative_to(ROOT))
            if frozen.get(rel(__file__)) != sha256_file(__file__):
                raise SystemExit("ABORT: evaluate_v5.py is not frozen by hash in v5/FREEZE.json")
            if frozen.get("real-agent-eval/v5/frozen-bin/bran") != sha256_file(args.bin):
                raise SystemExit("ABORT: --bin is not the frozen binary of v5/FREEZE.json")
            if sorted(set(args.accepted_checker or [])) != [PREREG_CHECKER]:
                raise SystemExit(f"ABORT: conf accepts exactly the prereg checker {PREREG_CHECKER}")
            if (args.be_g_config, args.be_config, args.best_model) != (PREREG_CONFIGS["BE-G"], PREREG_CONFIGS["BE"], PREREG_BEST):
                raise SystemExit(f"ABORT: conf configurations must be the prereg ones {PREREG_CONFIGS}, BEST {PREREG_BEST}")
            if local_arm == "confirmatory" and "BE-G-L" not in expect_tpl:
                raise SystemExit("ABORT: confirmatory local arm needs --expect-template BE-G-L=<prereg sha256>")
    if args.checks and not args.accepted_checker:
        raise SystemExit("ABORT: --checks given without --accepted-checker (labels would all score as unchecked)")
    for c in (args.be_config, args.be_g_config):
        if c:
            parse_config(c)
    if args.be_g_config and not parse_config(args.be_g_config)[2]:
        raise SystemExit("ABORT: --be-g-config must be a gated configuration")

    judge = load_judge(args.judge)
    if args.judge_local:
        load_judge(args.judge_local, rename={"J": "J_local", "RS": "RS_local"}, out=judge)
    for m, jid in expect_jid.items():
        rows_m = list(judge.get((m, 0), {}).values())
        bad = [e["id"] for e in rows_m if e.get("judge_id") != jid]
        if bad or not rows_m:
            raise SystemExit(f"ABORT: {m} rows do not all carry judge_id {jid} ({len(bad)} of {len(rows_m)})")
    captures = load_captures(args.captures)
    ctx = Ctx(args, captures, load_checks(args.checks), judge)
    ctx_local = (Ctx(args, captures, load_checks(args.local_checks), judge, accepted=[args.local_accepted_checker])
                 if args.local_checks else None)
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx.rdir = out_dir / "rust"
    if ctx_local:
        ctx_local.rdir = out_dir / "rust_local"
    items = load_items(args.items)
    raws = {f.stem: jload(f) for f in sorted(raw_dir.glob("*.json"))}
    unknown = sorted(set(raws) - set(items))
    if unknown:
        raise SystemExit(f"ABORT: raw records for unknown items: {unknown[:5]}")
    ids = sorted(raws, key=lambda i: (items[i].get("order", 0), i))
    recs = [prepare_item(items[i], raws[i], ctx) for i in ids]
    for rec in recs:
        it, row = rec["item"], rec["row"]
        row["set"] = analysis_set(it, strict=args.split == "conf" and not args.synthetic_test)
        row["tier"] = it.get("tier", "")
        row["gold_refuted"] = int(it["answer_format"] == "supported_refuted" and it["gold"]["answer"] == "REFUTED")
        row["disagreement"] = int(row["eligible"] and row["n_distinct"] >= 2)
        row["F"], row["fhat_pairs"] = f_and_pairs(rec, ctx.accepted)
        rec["check_keys"] = sorted({a["check"] for v in rec["parsed"] for a in v["audit"] if a.get("check")})
    rows = [r["row"] for r in recs]
    pa = per_agent(recs)
    best = args.best_model or max(sorted(pa), key=lambda a: pa[a]["correct"])

    # pass 1: B0 and the BE grid (dev) or the frozen BE and BE-G (conf)
    configs = FULL_GRID if args.split == "dev" else list(dict.fromkeys([args.be_g_config, args.be_config]))
    elig_recs = [r for r in recs if r["row"]["eligible"]]
    for rec in elig_recs:
        rec["B0"] = reduce_method(rec, "B0", None, ctx, "B0")
        rec["grid"] = {cfg: reduce_method(rec, "BE", cfg, ctx, "BE_" + cfg.replace(":", "_").replace("/", "_"))
                       for cfg in configs}
        python_methods(rec, ctx, best)
    elig = [r["row"] for r in elig_recs]
    dec_recs = [r for r in elig_recs if r["row"]["decisive"]]
    dec = [r["row"] for r in dec_recs]
    grid = []
    for cfg in configs:
        for r in elig_recs:
            r["row"]["_g"] = r["grid"][cfg]["correct"]
        ov = overturn(dec, "_g")
        grid.append({"config": cfg, "changed_fields": changed_fields(cfg), "dev_informed": cfg in DEV_INFORMED,
                     "gated": parse_config(cfg)[2], "nei": parse_config(cfg)[1],
                     "policy_template_sha256": template_sha("BE", cfg, ctx.accepted), "b": ov["b"], "c": ov["c"],
                     "b_minus_c": ov["b"] - ov["c"], "psi": (ov["b"] + ov["c"]) / len(dec) if dec else None,
                     "policy_hash": elig_recs[0]["grid"][cfg]["policy_hash"] if elig_recs else None,
                     "policy_hashes_distinct_items": len({r["grid"][cfg]["policy_hash"] for r in elig_recs})})
    for r in elig_recs:
        r["row"].pop("_g", None)
    if args.split == "dev":
        # §5.1 rule over the original six only (dev_informed configs are never selected as BE)
        selected = sorted((g for g in grid if g["config"] in GRID),
                          key=lambda g: (-g["b_minus_c"], g["changed_fields"], GRID.index(g["config"])))[0]["config"]
        # FRAMING §3.4 rule within gated templates: largest b - c, then smaller c, then fewer
        # changed fields, then full-grid order
        selected_g = sorted((g for g in grid if g["gated"]),
                            key=lambda g: (-g["b_minus_c"], g["c"], g["changed_fields"],
                                           FULL_GRID.index(g["config"])))[0]["config"]
    else:
        selected, selected_g = args.be_config, args.be_g_config

    # policy templates (prereg §2, §11 item 1)
    templates = {"B0": template_sha("B0", None, ctx.accepted), "BE": template_sha("BE", selected, ctx.accepted),
                 "BE-G": template_sha("BE", selected_g, ctx.accepted), "EO": template_sha("EO", selected, ctx.accepted)}
    if ctx_local:
        templates["BE-G-L"] = template_sha("BE", selected_g, ctx_local.accepted)
    tcheck = {"against_prereg": ctx.accepted == [PREREG_CHECKER], "mismatches": []}
    if tcheck["against_prereg"]:
        for k, v in PREREG_TEMPLATES.items():
            if templates[k] != v:
                tcheck["mismatches"].append({"method": k, "got": templates[k], "prereg": v})
    for k, v in expect_tpl.items():
        if templates.get(k) != v:
            tcheck["mismatches"].append({"method": k, "got": templates.get(k), "expected": v})
    # in dev the selected configs may legitimately differ from the prereg ones; conf must match
    if tcheck["mismatches"] and (args.split == "conf" or expect_tpl):
        bad = [m for m in tcheck["mismatches"] if args.split == "conf" or m["method"] in expect_tpl]
        if bad:
            raise SystemExit(f"ABORT: policy_template_sha256 mismatch: {bad}")
    tcheck["ok"] = not tcheck["mismatches"]

    # pass 2: BE = selected, BE-G = selected_g, EO on BE's mode / NEI, replay identity, local arm
    replay_ok = 0
    replay = Counter()
    be_wall = []
    overturns, seps, seps_g, loao = [], [], [], []
    t_loao = 0.0
    for rec in elig_recs:
        row, be, bg = rec["row"], rec["grid"][selected], rec["grid"][selected_g]
        row["B0"], row["B0_obj"] = rec["B0"]["correct"], rec["B0"]["obj"]
        row["BE"], row["BE_obj"] = be["correct"], be["obj"]
        row["BE_in_deadband"] = int(bool(be["sel"] and be["sel"]["in_deadband"]))
        row["BE_policy_hash"] = be["policy_hash"]
        gated_row(rec, row, bg, "BE-G", "D")
        row["BE-G_wall_s"], row["BE_wall_s"] = bg["wall_s"], be["wall_s"]
        for cfg in configs:
            row["G:" + cfg] = rec["grid"][cfg]["correct"]
            row["G:" + cfg + "_obj"] = rec["grid"][cfg]["obj"]
        eo = reduce_method(rec, "EO", selected, ctx, "EO")
        row["EO"], row["EO_obj"] = eo["correct"], eo["obj"]
        same = replay_same(args.bin, be)
        replay_ok += int(same)
        row["BE_replay_identical"] = int(same)
        row["BE-G_replay_identical"] = int(replay_same(args.bin, bg))
        replay["BE"] += int(same)
        replay["BE-G"] += row["BE-G_replay_identical"]
        be_wall.append(be["wall_s"])
        if ctx_local:
            recl = prepare_item(rec["item"], raws[rec["item"]["id"]], ctx_local)
            rec["local"] = recl
            bl = reduce_method(recl, "BE", selected_g, ctx_local, "BEGL_" + selected_g.replace(":", "_").replace("/", "_"))
            rec["BEGL"] = bl
            gated_row(recl, row, bl, "BE-G-L", "D-L")
            row["BE-G-L_wall_s"] = bl["wall_s"]
            row["BE-G-L_replay_identical"] = int(replay_same(args.bin, bl))
            replay["BE-G-L"] += row["BE-G-L_replay_identical"]
            vl, fb = vv_value(recl, ctx_local.accepted, row["MAJ_obj"])
            row["VV-L"], _ = object_correct(rec, vl)
            row["VV-L_obj"], row["VV-L_fallback"] = vl, fb
            row["F_L"], row["fhat_pairs_L"] = f_and_pairs(recl, ctx_local.accepted)
            recl["check_keys"] = sorted({a["check"] for v in recl["parsed"] for a in v["audit"] if a.get("check")})
        if row["decisive"]:
            s = separation(rec, be["sel"])
            seps.append(s)
            row["BE_separation_q"] = s
            seps_g.append(separation(rec, bg["sel"]))
        if row["BE_obj"] != row["MAJ_obj"] and be["winner"]:
            w = rec["by_id"][be["winner"]]
            overturns.append({"id": row["id"], "source": row["source"], "decisive": row["decisive"],
                              "MAJ_obj": row["MAJ_obj"], "MAJ_correct": row["MAJ"],
                              "BE_obj": row["BE_obj"], "BE_correct": row["BE"], "winner": be["winner"],
                              "winner_agent": w["agent"], "winner_score_q": be["sel"]["scores_q"][be["winner"]],
                              "winner_citations": w["audit"], "policy_hash": be["policy_hash"],
                              "root_hash": be["root_hash"]})
        if row["disagreement"] and not args.no_loao:
            t0 = time.perf_counter()
            lo = leave_one_out(rec, selected_g, ctx, bg["obj"])
            t_loao += time.perf_counter() - t0
            loao += lo
    if args.split == "conf":
        for m, k in replay.items():
            if k != len(elig_recs):
                raise SystemExit(f"ABORT: {m} replay not byte-identical on {len(elig_recs) - k} items")

    # statistics
    res = {"split": args.split, "synthetic": bool(args.synthetic_test),
           "provenance": provenance(args, ctx, ctx_local, {"configs": {"BE": selected, "BE-G": selected_g},
                                                           "policy_template_sha256": templates,
                                                           "template_check": tcheck}),
           "n_items": len(rows), "eligible": len(elig), "decisive": len(dec),
           "yield": len(dec) / len(rows) if rows else None,
           "decisive_by_source": dict(Counter(r["source"] for r in dec)),
           "exclusions_fewer_than_2_parsed": dict(Counter(r["source"] for r in rows if not r["eligible"])),
           "per_agent": pa, "BEST_agent": best, "BE_config": selected, "BE_G_config": selected_g, "BE_grid": grid,
           "counts": dict(ctx.counts), "local_counts": dict(ctx_local.counts) if ctx_local else None}
    # the design's (v3/SWARM3_DESIGN.md) BE-only statistics, kept for continuity with dev outputs
    h1 = paired(dec, "BE", "MAJ", args.bootstrap, args.seed)
    h1["reject"] = h1["p_exact_mcnemar"] <= 0.05
    ov = overturn(dec, "BE")
    res["design_v3"] = {"note": "the design's H1-H3 (superseded by PREREGISTRATION.md §2; see `prereg`)",
                        "H1": {"contrast": "BE vs MAJ on decisive conflicts (exact two-sided McNemar on b, c)", **h1,
                               "net_gain": ov["net_gain"], "p_w": ov["p_w"], "p_w_wilson95": ov["p_w_wilson95"],
                               "q_r": ov["q_r"], "q_r_wilson95": ov["q_r_wilson95"],
                               "majority_wrong": ov["base_wrong"], "majority_right": ov["base_right"]}}
    h2 = paired(dec, "BE", "J", args.bootstrap, args.seed)
    res["design_v3"]["H2"] = {"contrast": "BE vs J on decisive conflicts (non-inferiority, then superiority)", **h2,
                              **noninferiority(h2), "J_fallbacks_decisive": sum(r["J_fallback"] for r in dec)}
    res["design_v3"]["H3"] = h3(recs, elig_recs, ctx, replay_ok, be_wall)
    res["accuracy_decisive"] = {m: sum(r[m] for r in dec) / len(dec) if dec else None for m in METHODS}
    res["accuracy_eligible"] = {m: sum(r[m] for r in elig) / len(elig) if elig else None for m in METHODS}
    res["overturn_vs_MAJ"] = {m: overturn(dec, m) for m in METHODS if m != "MAJ"}
    res["BE_vs"] = {m: paired(dec, "BE", m) for m in METHODS if m != "BE"}
    by_src = {}
    for src in sorted({r["source"] for r in dec}):
        sub = [r for r in dec if r["source"] == src]
        by_src[src] = {"n": len(sub), "accuracy": {m: sum(r[m] for r in sub) / len(sub) for m in METHODS},
                       "BE_vs_MAJ": paired(sub, "BE", "MAJ"), "overturn": overturn(sub, "BE")}
    res["by_source"] = by_src
    seps_ok = [s for s in seps if s is not None]
    res["S4_separation"] = {"decisive_with_slot": len(seps_ok), "separated": sum(1 for s in seps_ok if s > SEP_DELTA_Q),
                            "delta": SEP_DELTA_Q / 10000}
    res["fallbacks"] = {k: sum(r.get(k, 0) for r in dec) for k in ("VV_fallback", "BEST_fallback", "J_fallback", "RS_missing")}
    res["majority_tied_decisive"] = sum(r["majority_tied"] for r in dec)
    res["objects_with_mixed_member_correctness"] = sum(r["mixed_objects"] for r in elig)
    res["mirror_check"] = {"slots_checked": ctx.counts["mirror_checked"] + (ctx_local.counts["mirror_checked"] if ctx_local else 0),
                           "mismatches": 0}
    if args.split == "dev":
        res["dev_informed"] = gate_analysis(dec_recs, elig_recs, ctx, selected_g)
    names = {"BE": selected, "BE-G": selected_g, "BE-G-L": selected_g if ctx_local else None}
    res["prereg"] = prereg_analysis(args, recs, elig_recs, ctx, ctx_local, names, local_arm, templates, tcheck,
                                    {"replay": dict(replay), "loao": loao, "loao_wall_s": t_loao, "seps_g": seps_g,
                                     "seps": seps})
    if args.split == "dev":
        gate = dev_gate(recs, rows, dec, pa, ctx)
        bm = next(g for g in grid if g["config"] == selected)
        import power_v5
        gate["stopping_rule"] = power_v5.stopping_rule(bm["psi"] or 0.0, res["yield"] or 0.0)
        res["dev_gate"] = gate
        with open(out_dir / "dev_gate_v5.json", "w") as f:
            json.dump(gate, f, indent=2)
    local_cols = ["BE-G-L", "BE-G-L_obj", "BE-G-L_stage", "D-L", "VV-L", "BE-G-L_replay_identical", "F_L"] if ctx_local else []
    cols = (["id", "source", "stratum", "set", "tier", "n_parsed", "n_correct", "n_distinct", "decisive", "disagreement",
             "majority_tied", "BE_in_deadband", "BE_replay_identical", "BE-G_replay_identical", "BE_separation_q"]
            + METHODS + ["BE-G", "D", "CV", "CONF", "CB-S", "J_local", "MAJ_early", "J_nullwrong", "J_local_nullwrong"]
            + [m + "_obj" for m in ("MAJ", "B0", "BE", "BE-G", "D", "EO", "VV", "CV", "CONF", "J", "J_local", "RS", "CB-S")]
            + ["BE-G_stage", "BE-G_overturned", "F", "fhat_pairs", "J_fallback", "J_local_fallback", "CB-S_missing"]
            + local_cols)
    cols += [f"G:{cfg}{s}" for cfg in configs for s in ("", "_obj")]
    write_csv(out_dir / "paired_decisions_v5.csv", elig, cols)
    write_csv(out_dir / "items_v5.csv", rows, ["id", "source", "stratum", "set", "tier", "n_responses", "n_parsed",
                                               "n_correct", "n_distinct", "eligible", "decisive", "disagreement"])
    with open(out_dir / "overturns_v5.jsonl", "w") as f:
        for o in overturns:
            f.write(json.dumps(o, sort_keys=True) + "\n")
    with open(out_dir / "loao_v5.jsonl", "w") as f:
        for o in loao:
            f.write(json.dumps(o, sort_keys=True) + "\n")
    pr = res["prereg"]
    with open(out_dir / "witness_sample_v5.jsonl", "w") as f:
        for o in pr.pop("_witness_sample"):
            f.write(json.dumps(o, sort_keys=True) + "\n")
    with open(out_dir / "planned_subsamples_v5.json", "w") as f:
        json.dump(pr["H5"]["replay"]["planned_subsamples"], f, indent=1)
    with open(out_dir / "figures_v5.json", "w") as f:
        json.dump(pr["figures"], f, indent=2, sort_keys=True)
    with open(out_dir / "evaluation_v5.json", "w") as f:
        json.dump(res, f, indent=2, sort_keys=True)
    print(json.dumps({k: res[k] for k in ("split", "n_items", "eligible", "decisive", "BE_config", "BE_G_config")}, indent=1))
    h = pr["H1"]
    print(json.dumps({k: {x: h[k][x] for x in ("n", "b", "c", "p_exact_mcnemar", "reject", "reading")} for k in ("H1a", "H1b")}))
    return 0


# ── preregistered analysis (PREREGISTRATION.md §2, §7, §10) ─────

def _subset(rows, s):
    return list(rows) if s == "pooled" else [r for r in rows if r["set"] == s]


def _test(rows, m, base, n_boot, seed):
    pr = paired(rows, m, base, n_boot, seed)
    o = overturn(rows, m, base)
    pr.update({"p_w": o["p_w"], "p_w_wilson95": o["p_w_wilson95"], "q_r": o["q_r"], "q_r_wilson95": o["q_r_wilson95"],
               "base_wrong": o["base_wrong"], "base_right": o["base_right"], "net_gain": o["net_gain"],
               "direction": direction(pr)})
    return pr


def prereg_analysis(args, recs, elig_recs, ctx, ctx_local, names, local_arm, templates, tcheck, extra):
    nb, seed = args.bootstrap, args.seed
    elig = [r["row"] for r in elig_recs]
    dec = [r for r in elig if r["decisive"]]
    P, T = _subset(dec, "P"), _subset(dec, "T")
    local = ctx_local is not None
    avail = {"J": any(r["J_has_row"] for r in elig), "RS": any(r["RS_has_row"] for r in elig),
             "CB-S": any(r["CB-S_has_row"] for r in elig), "J_local": any(r["J_local_has_row"] for r in elig),
             "BE-G-L": local, "VV-L": local, "D-L": local}
    methods = (["MAJ", "BE-G", "BE", "B0", "EO", "VV", "CV", "CONF", "BEST", "D", "ORC"]
               + [m for m in ("BE-G-L", "VV-L", "D-L") if local] + [m for m in JUDGES if avail[m]])
    out = {"note": ("PREREGISTRATION.md (draft) §2 hypotheses; on dev every number is dev-informed and descriptive"
                    if args.split == "dev" else "PREREGISTRATION.md §2 confirmatory analysis"),
           "methods": {"BE-G": names["BE-G"], "BE": names["BE"], "BE-G-L": names["BE-G-L"],
                       "EO_at": names["BE"], "BEST": args.best_model or None},
           "policy_template_sha256": templates, "template_check": tcheck, "available": avail,
           "methods_reported": methods}
    # analysis sets
    sets = {}
    for s in SETS:
        rs = [r["row"] for r in recs] if s == "pooled" else [r["row"] for r in recs if r["row"]["set"] == s]
        e = [r for r in rs if r["eligible"]]
        d = [r for r in e if r["decisive"]]
        sets[s] = {"items": len(rs), "eligible": len(e), "decisive": len(d), "disagreement": sum(r["disagreement"] for r in e),
                   "yield": len(d) / len(rs) if rs else None, "by_source": dict(Counter(r["source"] for r in d)),
                   "tiers": dict(Counter(r["tier"] for r in rs))}
    out["analysis_sets"] = {"rule": ("tier primary -> P, tier tqa_stratum -> T (prereg §6.3); items without those tiers: "
                                     "TruthfulQA -> T, other sources -> P"), "never_pooled_for_tests": True, **sets}

    # H1 (Holm)
    t = {"H1a": _test(P, "BE-G", "MAJ", nb, seed), "H1b": _test(P, "BE", "MAJ", nb, seed)}
    t["H1a"]["contrast"], t["H1b"]["contrast"] = "BE-G vs MAJ on P", "BE vs MAJ on P"
    hm = holm({k: v["p_exact_mcnemar"] for k, v in t.items()}, H1_ALPHA)
    for k, v in t.items():
        v["holm"] = hm[k]
        v["reject"] = hm[k]["reject"]
        v["reading"] = ("not rejected" if not v["reject"] else "better" if v["b"] > v["c"] else "worse")
    t["family"] = {"procedure": "Holm, family-wise alpha 0.05 (first step 0.025, second 0.05 only if the first rejects)",
                   "order": sorted(hm, key=lambda k: hm[k]["rank"])}
    out["H1"] = t

    # H3 no-harm
    def h3a(m):
        right = [r for r in P if r["MAJ"]]
        n_r = len(right)
        c = sum(1 for r in right if not r[m])
        ub = cp_upper(c, n_r, H3A_ALPHA)
        cmax = -1
        while n_r and cp_upper(cmax + 1, n_r, H3A_ALPHA) < H3A_BOUND:
            cmax += 1
        return {"set": "P", "method": m, "n_R": n_r, "c": c, "q_r": c / n_r if n_r else None,
                "cp_upper_97_5": ub, "bound": H3A_BOUND, "one_sided_alpha": H3A_ALPHA,
                "reject": bool(ub is not None and ub < H3A_BOUND), "c_max_that_rejects": cmax if cmax >= 0 else None}

    def h3b(m):
        pr = _test(T, m, "MAJ", nb, seed)
        lo = pr["newcombe_ci95"][0] if pr["newcombe_ci95"] else None
        rej = bool(lo is not None and lo > H3B_MARGIN)
        return {"set": "T", **pr, "margin": H3B_MARGIN, "one_sided_alpha": 0.025, "newcombe_lower": lo, "reject": rej,
                "reading": ("non-inferior" if rej else "not shown; point estimate negative"
                            if (pr["diff"] or 0) < 0 else "not shown"),
                "power_warning": ("power about 0.81 if BE-G and MAJ never disagree on T, 0.31 at b = c = 2%, "
                                  "0.08 at dev's rate; a non-rejection is 'not shown', never harm, unless the estimate is negative")}
    out["H3"] = {"H3a": h3a("BE-G"), "H3b": h3b("BE-G"),
                 "BE_descriptive": {"H3a": h3a("BE"), "H3b": h3b("BE")}}

    # H2 local arm (fixed sequence)
    out["H2"] = h2_local(P, elig_recs, ctx, ctx_local, local_arm, args, nb, seed, avail)

    # §2.4 references against MAJ and BE-G
    refs = {}
    for s in SETS:
        rows = _subset(dec, s)
        fam = [m for m in REF_FAMILY if m in methods]
        vs_maj = {m: _test(rows, m, "MAJ", 0, seed) for m in fam + [m for m in ("J_local", "BEST", "VV", "VV-L") if m in methods]}
        vs_bg = {m: _test(rows, "BE-G", m, 0, seed) for m in fam + [m for m in ("J_local", "BEST", "VV") if m in methods]}
        hm = holm({m: vs_maj[m]["p_exact_mcnemar"] for m in fam}, 0.05) if fam and s != "pooled" else {}
        for m in fam:
            if m in hm:
                vs_maj[m]["p_holm_ref_family"] = hm[m]["p_holm"]
        refs[s] = {"family": fam, "vs_MAJ": vs_maj, "BE-G_vs": vs_bg,
                   "not_run": [m for m in REF_FAMILY + ["J_local"] if m not in methods]}
    out["references"] = refs

    # accuracy and overturn rates per set
    out["accuracy"], out["overturn_vs_MAJ"], out["overturn_vs_D"] = {}, {}, {}
    for s in SETS:
        rows = _subset(dec, s)
        erows = _subset(elig, s)
        out["accuracy"][s] = {"decisive": {m: (sum(r[m] for r in rows) / len(rows) if rows else None) for m in methods},
                              "eligible": {m: (sum(r[m] for r in erows) / len(erows) if erows else None) for m in methods},
                              "n_decisive": len(rows), "n_eligible": len(erows)}
        out["overturn_vs_MAJ"][s] = {m: overturn(rows, m) for m in methods if m != "MAJ"}
        out["overturn_vs_D"][s] = {"BE-G": overturn(rows, "BE-G", "D")}
        if local:
            out["overturn_vs_D"][s]["BE-G-L"] = overturn(rows, "BE-G-L", "D-L")

    # H4 gate soundness
    rate = parse_rate(args.fhat_rate) or (parse_rate(FHAT_RATE[ctx.accepted[0]])
                                         if len(ctx.accepted) == 1 and ctx.accepted[0] in FHAT_RATE else None)
    rate_l = parse_rate(args.local_fhat_rate) if local else None
    out["H4"] = {"theorem": "c_D <= F (v3/GATE_SPEC.md §3)", "fhat_rate": rate, "local_fhat_rate": rate_l}
    for s in ("P", "T", "pooled"):
        rows = _subset(dec, s)
        out["H4"][s] = {"BE-G": h4_block(rows, "BE-G", "D", "F", "fhat_pairs", rate)}
        if local:
            out["H4"][s]["BE-G-L"] = h4_block(rows, "BE-G-L", "D-L", "F_L", "fhat_pairs_L", rate_l)
    out["H4"]["harm_bound_holds"] = all(v["harm_bound_holds"] for s in ("P", "T") for v in out["H4"][s].values())
    out["H4"]["implementation_defect"] = not out["H4"]["harm_bound_holds"]

    # H5 descriptive
    h5 = {}
    h5["gap_closed"] = {s: gap_closed(_subset(dec, s), [m for m in GAP_METHODS if m in methods],
                                      [r for r in GAP_REFS if r in methods], nb, seed) for s in SETS}
    h5["cost"], h5["latency"] = cost_latency(recs, ctx, ctx_local, avail)
    h5["replay"] = replay_block(elig_recs, ctx, extra, avail, h5["cost"])
    h5["audit"] = audit_size(elig_recs, ctx, names)
    h5["majority_following"] = {s: majority_following(_subset(dec, s), avail) for s in SETS}
    h5["pairs"] = {s: {"BE-G_vs_VV": _test(_subset(dec, s), "BE-G", "VV", 0, seed),
                       "BE_vs_EO": _test(_subset(dec, s), "BE", "EO", 0, seed)} for s in SETS}
    h5["subgroups"] = subgroups(dec, methods)
    out["H5"] = h5

    # sensitivity (§10)
    sens = {"null_judge_scored_wrong": {}, "popqa_excluded": {}, "MAJ_earliest_arrival_ties": {}, "against_D": {}}
    PnoPop = [r for r in P if r["source"] != "popqa"]
    for h, m in (("H1a", "BE-G"), ("H1b", "BE")):
        sens["popqa_excluded"][h] = _test(PnoPop, m, "MAJ", 0, seed)
        sens["MAJ_earliest_arrival_ties"][h] = _test(P, m, "MAJ_early", 0, seed)
    sens["against_D"]["BE-G"] = overturn(P, "BE-G", "D")
    for s in ("P", "T"):
        rows = _subset(dec, s)
        sens["null_judge_scored_wrong"][s] = {
            m: {"vs_MAJ": _test(rows, m + "_nullwrong", "MAJ", 0, seed),
                "BE-G_vs": _test(rows, "BE-G", m + "_nullwrong", 0, seed),
                "nulls": sum(r[m + "_fallback"] for r in rows)}
            for m in ("J", "J_local") if avail[m]}
    if local and avail["J_local"]:
        pr = paired(P, "BE-G-L", "J_local_nullwrong")
        sens["null_judge_scored_wrong"]["H2b_NI"] = {**pr, "newcombe_lower": pr["newcombe_ci95"][0] if pr["newcombe_ci95"] else None}
    ws = witness_sample(elig_recs, ctx, names)
    sens["witness_sample"] = {"file": "witness_sample_v5.jsonl", "n": len(ws), "seed": "v5-witness-sample",
                              "note": "blinded BE-G overturn witnesses for human / simulated labelling (kappa vs G-AK)"}
    out["_witness_sample"] = ws
    out["sensitivity"] = sens

    # also reported (§7)
    seps_g = [s for s in extra["seps_g"] if s is not None]
    out["also"] = {
        "S4_separation": {"BE-G": {"decisive_with_slot": len(seps_g), "separated": sum(1 for s in seps_g if s > SEP_DELTA_Q)},
                          "BE": {"decisive_with_slot": len([s for s in extra["seps"] if s is not None]),
                                 "separated": sum(1 for s in extra["seps"] if s is not None and s > SEP_DELTA_Q)},
                          "delta": SEP_DELTA_Q / 10000},
        "checks": check_stats(recs, ctx),
        "local_checks": check_stats([r["local"] for r in elig_recs], ctx_local) if local else None,
        "evidence_availability": evidence_availability(recs, ctx),
        "gate_stage_counts": {s: dict(Counter(r["BE-G_stage"] for r in _subset(dec, s))) for s in SETS},
        "per_agent_decisive_accuracy": {s: per_agent_set(recs, s) for s in SETS},
        "fallbacks": {s: {k: sum(r.get(k, 0) for r in _subset(dec, s)) for k in
                          ("VV_fallback", "CV_fallback", "BEST_fallback", "J_fallback", "J_local_fallback",
                           "RS_missing", "CB-S_missing")} for s in SETS},
        "majority_tied_decisive": {s: sum(r["majority_tied"] for r in _subset(dec, s)) for s in SETS},
    }
    out["figures"] = figures(out, methods)
    return out


def h2_local(P, elig_recs, ctx, ctx_local, local_arm, args, nb, seed, avail):
    if ctx_local is None:
        return {"status": "not_run", "text": "not run: no local checks supplied", "confirmatory": False}
    conf = local_arm == "confirmatory"
    a = _test(P, "BE-G-L", "MAJ", nb, seed)
    a_rej = bool(a["p_exact_mcnemar"] <= H2_ALPHA and a["b"] > a["c"])
    out = {"status": local_arm, "confirmatory": conf,
           "text": None if conf else "not run as confirmatory; local checker unvalidated",
           "sequence": "H2a -> H2b-NI -> H2b-S, each tested only if the previous one rejects (with b > c)",
           "H2a": {**a, "contrast": "BE-G-L vs MAJ on P", "alpha": H2_ALPHA, "tested": True, "reject": a_rej}}
    if avail["J_local"]:
        b = _test(P, "BE-G-L", "J_local", nb, seed)
        lo = b["newcombe_ci95"][0] if b["newcombe_ci95"] else None
        ni = bool(lo is not None and lo > H2_NI_MARGIN)
        out["H2b_NI"] = {**b, "contrast": "BE-G-L vs J_local on P", "margin": H2_NI_MARGIN, "newcombe_lower": lo,
                         "tested": a_rej, "reject": bool(a_rej and ni), "statistic_rejects": ni}
        sup = bool(b["p_exact_mcnemar"] <= H2_ALPHA and b["b"] > b["c"])
        out["H2b_S"] = {"contrast": "BE-G-L vs J_local superiority", "p_exact_mcnemar": b["p_exact_mcnemar"],
                        "b": b["b"], "c": b["c"], "alpha": H2_ALPHA, "tested": bool(a_rej and ni),
                        "reject": bool(a_rej and ni and sup), "statistic_rejects": sup}
    else:
        out["H2b_NI"] = out["H2b_S"] = {"tested": False, "reject": False, "text": "no J_local rows"}
    out["diagnostics"] = local_diagnostics(elig_recs, ctx, ctx_local, args)
    return out


def _base_model(name):
    return (name or "").split(":")[0].split("_")[0].lower() or None


def local_diagnostics(elig_recs, ctx, ctx_local, args):
    """J_local self-preference (rate of selecting its own agent's answer vs the other judges' rate
    on the same items) and the shared-model flag."""
    agent = args.local_judge_agent
    items = []
    for rec in elig_recs:
        row = rec["row"]
        if row["set"] != "P" or not row["disagreement"]:
            continue
        own = [v for v in rec["parsed"] if v["agent"] == agent]
        if own and row["J_local_has_row"] and not row["J_local_fallback"]:
            items.append((row, own[0]["parsed"]))
    rate = lambda m: (sum(1 for r, o in items if r.get(m + "_obj") == o and not r.get(m + "_fallback", 0)) / len(items)
                      if items else None)
    cmodels = {e["checker"].get("model") for e in ctx_local.checks.values()}
    jmodels = {e.get("model") for e in ctx.judge.get(("J_local", 0), {}).values() if e.get("model")}
    amodels = {v["model"] for rec in elig_recs for v in rec["parsed"] if v["agent"] == agent and v.get("model")}
    bases = {_base_model(m) for m in cmodels | jmodels | amodels if m}
    shared = bool(cmodels and jmodels and amodels and len(bases) == 1)
    return {"self_preference": {"agent": agent, "items": len(items), "J_local": rate("J_local"), "J": rate("J"),
                                "RS_value_match": rate("RS"), "CB-S_value_match": rate("CB-S"),
                                "set": "P disagreement items where the agent parsed and J_local decided"},
            "shared_model": {"local_checker_models": sorted(m for m in cmodels if m),
                             "J_local_models": sorted(jmodels), "agent_models": sorted(amodels),
                             "all_same_model": shared,
                             "note": ("the local checker, J_local and an agent are the same model; the H2 paragraph says so"
                                      if shared else ("J_local model not recorded in the rows" if not jmodels else None))}}


def h4_block(rows, m, d, fkey, pkey, rate):
    F_items = sorted(r["id"] for r in rows if r[fkey])
    cD_items = sorted(r["id"] for r in rows if r[d] and not r[m])
    c_items = sorted(r["id"] for r in rows if r["MAJ"] and not r[m])
    out = {"n": len(rows), "F": len(F_items), "F_items": F_items, "c_D": len(cD_items), "c_D_items": cD_items,
           "b_D": sum(1 for r in rows if r[m] and not r[d]), "c_vs_MAJ": len(c_items), "c_vs_MAJ_items": c_items,
           "b_vs_MAJ": sum(1 for r in rows if r[m] and not r["MAJ"]),
           "harm_bound_holds": set(cD_items) <= set(F_items),
           "c_vs_MAJ_not_in_F": sorted(set(c_items) - set(F_items)),
           "c_vs_MAJ_not_in_F_tied": sum(1 for r in rows if r["id"] in set(c_items) - set(F_items) and r["majority_tied"]),
           "checked_incorrect_pairs": sum(r[pkey] for r in rows)}
    if rate:
        out["F_hat"] = sum(1 - (1 - rate["rate"]) ** r[pkey] for r in rows)
        out["F_vs_F_hat"] = "validation metrics predict deployment harm (descriptive)"
    else:
        out["F_hat"] = None
    return out


def _check_cost(entries):
    tot = lambda k: sum(e.get(k) or 0 for e in entries) if any(e.get(k) is not None for e in entries) else None
    return {"usd": tot("cost_usd"), "model_calls": len(entries), "input_tokens": tot("input_tokens"),
            "output_tokens": tot("output_tokens"), "cache_creation_input_tokens": tot("cache_creation_input_tokens"),
            "cache_read_input_tokens": tot("cache_read_input_tokens"), "wall_ms": tot("duration_ms")}


def _per(d, n):
    return {k: (v / n if (v is not None and n) else None) for k, v in d.items()}


def cost_latency(recs, ctx, ctx_local, avail):
    """Uniform cost basis (prereg §7): every decider on every disagreement item; single-value
    items are `forced` with no call for every method. Checks: every de-duplicated cited
    (proposition, passage) check of the disagreement items; gold-shown diagnostic checks (never
    cited) are excluded and reported separately. Judges: their rows on disagreement items."""
    cost, lat = {}, {}
    cited_all = set().union(*[set(r["check_keys"]) for r in recs]) if recs else set()
    gold_only = [e for k, e in ctx.checks.items() if k not in cited_all]
    for s in SETS:
        drs = [r for r in recs if r["row"]["disagreement"] and (s == "pooled" or r["row"]["set"] == s)]
        n = len(drs)
        c, l = {"decisions": n, "forced_no_call_items": sum(1 for r in recs if r["row"]["eligible"] and not r["row"]["disagreement"]
                                                             and (s == "pooled" or r["row"]["set"] == s))}, {}
        keys = sorted({k for r in drs for k in r["check_keys"]})
        ents = [ctx.checks[k] for k in keys if k in ctx.checks]
        cc = _check_cost(ents)
        cc["checks_missing"] = len(keys) - len(ents)
        c["hosted_checks"] = {"total": cc, "per_decision": _per({k: v for k, v in cc.items() if k != "checks_missing"}, n),
                              "used_by": ["BE-G", "BE", "VV", "EO"]}
        for m in ("MAJ", "CV", "CONF", "BEST", "B0"):
            c[m] = {"model_calls_per_decision": 0.0, "usd_per_decision": 0.0, "note": "no call beyond the agents"}
        wall_r = [r["row"].get("BE-G_wall_s") for r in drs]
        for m in ("BE-G", "BE", "VV", "EO"):
            c[m] = {"usd_per_decision": c["hosted_checks"]["per_decision"]["usd"],
                    "model_calls_per_decision": c["hosted_checks"]["per_decision"]["model_calls"],
                    "input_tokens_per_decision": c["hosted_checks"]["per_decision"]["input_tokens"],
                    "output_tokens_per_decision": c["hosted_checks"]["per_decision"]["output_tokens"],
                    "cache_creation_tokens_per_decision": c["hosted_checks"]["per_decision"]["cache_creation_input_tokens"],
                    "reductions_per_decision": 1 if m in ("BE-G", "BE", "EO") else 0, "labels_reusable": True}
        # BE-G critical path: max check latency (checks run in parallel) + reducer wall time
        crit = []
        for r in drs:
            d = [ctx.checks[k].get("duration_ms") for k in r["check_keys"] if k in ctx.checks]
            d = [x for x in d if x is not None]
            crit.append((max(d) if d else 0) / 1000 + (r["row"].get("BE-G_wall_s") or 0))
        l["BE-G"] = {"critical_path_s": quantiles(crit), "reducer_wall_s": quantiles(wall_r)}
        l["BE"] = {"reducer_wall_s": quantiles([r["row"].get("BE_wall_s") for r in drs])}
        if ctx_local:
            lkeys = sorted({k for r in drs for k in r["local"]["check_keys"]})
            lents = [ctx_local.checks[k] for k in lkeys if k in ctx_local.checks]
            lc = _check_cost(lents)
            lc["checks_missing"] = len(lkeys) - len(lents)
            c["local_checks"] = {"total": lc, "per_decision": _per({k: v for k, v in lc.items() if k != "checks_missing"}, n),
                                 "local_wall_s_per_decision": (lc["wall_ms"] / 1000 / n) if (lc["wall_ms"] and n) else None,
                                 "used_by": ["BE-G-L", "VV-L"]}
            c["BE-G-L"] = {"usd_per_decision": 0.0, "model_calls_per_decision": c["local_checks"]["per_decision"]["model_calls"],
                           "local_wall_s_per_decision": c["local_checks"]["local_wall_s_per_decision"],
                           "reductions_per_decision": 1, "labels_reusable": True}
            critl = []
            for r in drs:
                d = [ctx_local.checks[k].get("duration_ms") for k in r["local"]["check_keys"] if k in ctx_local.checks]
                d = [x for x in d if x is not None]
                critl.append((max(d) if d else 0) / 1000 + (r["row"].get("BE-G-L_wall_s") or 0))
            l["BE-G-L"] = {"critical_path_s": quantiles(critl)}
        for m in JUDGES:
            if not avail.get(m):
                continue
            jr = [ctx.judge.get((m, 0), {}).get(r["item"]["id"]) for r in drs]
            have = [e for e in jr if e is not None]
            called = [e for e in have if e.get("status") not in ("forced", "no_candidates")]
            tot = lambda k: sum(e.get(k) or 0 for e in called)
            t = {"usd": tot("usd"), "model_calls": len(called), "input_tokens": tot("input_tokens"),
                 "output_tokens": tot("output_tokens"),
                 "cache_creation_input_tokens": (tot("cache_creation_input_tokens")
                                                 if any("cache_creation_input_tokens" in e for e in called) else None),
                 "wall_ms": tot("wall_ms")}
            c[m] = {"total": t, "per_decision": _per(t, n), "coverage": len(have) / n if n else None,
                    "rows": len(have), "cost_basis_complete": bool(n and len(have) == n),
                    "per_call_usd": t["usd"] / len(called) if called else None,
                    "per_call_wall_ms": t["wall_ms"] / len(called) if called else None}
            if m == "J_local":
                c[m]["local_wall_s_per_decision"] = (t["wall_ms"] / 1000 / n) if n else None
            l[m] = {"call_wall_ms": quantiles([e.get("wall_ms") for e in called])}
        cost[s], lat[s] = c, l
    cost["gold_shown_diagnostic_checks"] = {"note": "checks never cited by an agent (gold-shown availability diagnostic); "
                                                    "excluded from $/decision", **_check_cost(gold_only)}
    return cost, lat


def replay_block(elig_recs, ctx, extra, avail, cost):
    n = len(elig_recs)
    rp = extra["replay"]
    ids_dis = sorted(r["item"]["id"] for r in elig_recs if r["row"]["disagreement"])
    jregen_ids = random.Random("v5-jregen").sample(ids_dis, min(N_JREGEN, len(ids_dis)))
    loao_ids = random.Random("v5-loao").sample(ids_dis, min(N_LOAO_J, len(ids_dis)))
    out = {"identity": {m: {"identical": k, "checked": n, "all_identical": k == n} for m, k in rp.items()},
           "planned_subsamples": {"disagreement_items": len(ids_dis),
                                  "J_regeneration": {"seed": "v5-jregen", "rule": "random.Random(seed).sample(sorted ids, 200)",
                                                     "ids": sorted(jregen_ids)},
                                  "J_LOAO": {"seed": "v5-loao", "rule": "random.Random(seed).sample(sorted ids, 50)",
                                             "ids": sorted(loao_ids)}}}

    def agreement(m, run):
        base, rg = ctx.judge.get((m, 0), {}), ctx.judge.get((m, run), {})
        pairs = [(base[i], e) for i, e in rg.items() if i in base]
        ag = [int(a.get("status") == b.get("status") and a.get("selected") == b.get("selected")) for a, b in pairs]
        return {"run": run, "items": len(ag), "agreement": sum(ag) / len(ag) if ag else None,
                "condition": sorted({e.get("drift_condition") for e in rg.values() if e.get("drift_condition")}),
                "ids_match_planned": sorted(rg) == sorted(jregen_ids) if rg else None}
    out["J_regeneration"] = agreement("J", 1)
    out["J_local_drift"] = [agreement("J_local", r) for r in sorted({r for (m, r) in ctx.judge if m == "J_local" and r > 0})]
    # leave-one-agent-out
    lo = extra["loao"]
    items = sorted({o["id"] for o in lo})
    changed_items = sorted({o["id"] for o in lo if o["changed"]})
    out["LOAO"] = {"BE-G": {"items": len(items), "redecisions": len(lo), "model_calls": 0,
                            "changed_redecisions": sum(o["changed"] for o in lo),
                            "items_with_any_change": len(changed_items),
                            "change_rate": sum(o["changed"] for o in lo) / len(lo) if lo else None,
                            "wall_s_total": extra["loao_wall_s"],
                            "wall_s_per_item": extra["loao_wall_s"] / len(items) if items else None}}
    jl = ctx.judge.get(("J/loao", 0), {})
    jc = cost.get("pooled", {}).get("J") if avail.get("J") else None
    jout = {"subsample_rows": len(jl), "counterfactual_calls_per_item": 5}
    if jc:
        jout["counterfactual_usd_per_item"] = 5 * jc["per_call_usd"] if jc["per_call_usd"] is not None else None
        jout["counterfactual_wall_ms_per_item"] = 5 * jc["per_call_wall_ms"] if jc["per_call_wall_ms"] is not None else None
    if jl:
        base = ctx.judge.get(("J", 0), {})
        ch = [int(e.get("selected") != base.get(k.split("|")[0], {}).get("selected")) for k, e in jl.items()
              if k.split("|")[0] in base]
        jout.update(change_rate=sum(ch) / len(ch) if ch else None, compared=len(ch),
                    measured_usd=sum(e.get("usd") or 0 for e in jl.values()),
                    ids_match_planned=sorted({k.split("|")[0] for k in jl}) == sorted(loao_ids))
    out["LOAO"]["J"] = jout
    return out


def _witnesses(rec, res, ctx):
    gt = (res["sel"] or {}).get("gate")
    if not gt or not gt["overturned"]:
        return None
    wobj = rec["by_id"][res["winner"]]["parsed"]
    pks = sorted({a["passage_key"] for i in gt["witnesses"] if rec["by_id"][i]["parsed"] == wobj
                  for a in rec["by_id"][i]["audit"]
                  if a.get("support_label") == "supports" and a.get("support_status") == "ok" and a.get("accepted")})
    chars = 0
    for pk in pks:
        cap = ctx.captures.get(pk)
        ex = (cap[1].get("extraction") or {}) if cap else {}
        chars += int(ex.get("text_chars") or (cap[1].get("content_length") if cap else 0) or 0)
    return {"id": rec["item"]["id"], "value": wobj, "passages": pks, "n_passages": len(pks), "chars": chars}


def audit_size(elig_recs, ctx, names):
    out = {}
    for s in SETS:
        rs = [r for r in elig_recs if r["row"]["disagreement"] and (s == "pooled" or r["row"]["set"] == s)]
        ws = [w for w in (_witnesses(r, r["grid"][names["BE-G"]], ctx) for r in rs) if w]
        jt = [ (e.get("input_tokens") or 0) + (e.get("output_tokens") or 0)
               for e in (ctx.judge.get(("J", 0), {}).get(r["item"]["id"]) for r in rs)
               if e and e.get("status") not in ("forced", "no_candidates")]
        out[s] = {"BE-G_overturns": len(ws), "passages": quantiles([w["n_passages"] for w in ws]),
                  "chars": quantiles([w["chars"] for w in ws]), "J_context_tokens": quantiles(jt)}
    return out


def witness_sample(elig_recs, ctx, names):
    ws = [w for w in (_witnesses(r, r["grid"][names["BE-G"]], ctx) for r in elig_recs if r["row"]["decisive"]) if w]
    ws.sort(key=lambda w: w["id"])
    pick = random.Random("v5-witness-sample").sample(ws, min(N_WITNESS, len(ws)))
    out = []
    for w in sorted(pick, key=lambda w: w["id"]):
        rec = next(r for r in elig_recs if r["item"]["id"] == w["id"])
        out.append({"id": w["id"], "question": rec["item"]["question"], "value": w["value"],
                    "passage_keys": w["passages"], "label_for_human": None})   # blinded: no gold, no G-AK grade
    return out


def majority_following(rows, avail):
    mw = [r for r in rows if not r["MAJ"]]
    out = {"majority_wrong_items": len(mw)}
    for m in JUDGES:
        if not avail.get(m):
            continue
        if m in ("J", "J_local"):
            dec = [r for r in mw if r[m + "_has_row"] and not r[m + "_fallback"]]
        else:
            dec = [r for r in mw if r.get(m + "_obj") is not None]
        k = sum(1 for r in dec if r[m + "_obj"] == r["MAJ_obj"])
        out[m] = {"decided": len(dec), "follows_majority": k, "rate": k / len(dec) if dec else None,
                  "wilson95": wilson(k, len(dec))}
    return out


def subgroups(dec, methods):
    main = [m for m in ("MAJ", "BE-G", "BE", "BE-G-L", "VV", "J", "RS", "CB-S", "ORC") if m in methods]

    def block(rows):
        return {"n": len(rows), "accuracy": {m: (sum(r[m] for r in rows) / len(rows) if rows else None) for m in main},
                "BE-G_vs_MAJ": {k: v for k, v in paired(rows, "BE-G", "MAJ").items() if k in ("b", "c", "p_exact_mcnemar")},
                "BE_vs_MAJ": {k: v for k, v in paired(rows, "BE", "MAJ").items() if k in ("b", "c", "p_exact_mcnemar")}}
    out = {"by_source": {f"{s}:{src}": block([r for r in _subset(dec, s) if r["source"] == src])
                         for s in ("P", "T") for src in sorted({r["source"] for r in _subset(dec, s)})},
           "popqa_stratum": {st: block([r for r in dec if r["source"] == "popqa" and r["stratum"] == st])
                             for st in sorted({r["stratum"] for r in dec if r["source"] == "popqa"})},
           "scifact_refuted": block([r for r in dec if r["source"] == "scifact" and r["gold_refuted"]])}
    return out


def check_stats(recs, cx):
    keys = sorted({k for r in recs for k in r["check_keys"]})
    ents = [cx.checks[k] for k in keys if k in cx.checks]
    labels = Counter()
    for r in recs:
        for v in r["parsed"]:
            for a in v["audit"]:
                if a.get("check"):
                    labels[(a.get("support_label") or a.get("support_status") or "no_record")
                           + ("" if a.get("accepted", True) else ":unaccepted")] += 1
    return {"cited_checks": len(keys), "records": len(ents), "status": dict(Counter(e["status"] for e in ents)),
            "raw_labels": dict(Counter(e.get("label") for e in ents if e["status"] == "ok")),
            "mapped_labels_on_citations": dict(labels),
            "checker_ids": sorted({e["checker"]["checker_id"] for e in ents})}


def per_agent_set(recs, s):
    out = defaultdict(lambda: [0, 0])
    for r in recs:
        if not r["row"]["decisive"] or (s != "pooled" and r["row"]["set"] != s):
            continue
        for v in r["parsed"]:
            out[v["agent"]][0] += int(v["correct"])
            out[v["agent"]][1] += 1
    return {a: {"correct": k, "answered": n, "accuracy": k / n if n else None} for a, (k, n) in sorted(out.items())}


def figures(pr, methods):
    """Data for the planned figures: overturn chart, gap closed, cost vs replay."""
    order = [m for m in ("BE-G", "BE", "BE-G-L", "VV", "VV-L", "EO", "B0", "CV", "CONF", "BEST", "J", "RS", "CB-S", "J_local")
             if m in methods]
    fig = {"overturn_chart": {}, "gap_closed": {}, "cost_vs_replay": {}}
    for s in SETS:
        ov = pr["overturn_vs_MAJ"][s]
        fig["overturn_chart"][s] = [{"method": m, "b": ov[m]["b"], "c": ov[m]["c"], "p_w": ov[m]["p_w"],
                                     "p_w_wilson95": ov[m]["p_w_wilson95"], "q_r": ov[m]["q_r"],
                                     "q_r_wilson95": ov[m]["q_r_wilson95"]} for m in order]
        fig["gap_closed"][s] = [{"method": m, "ref": ref, "G": e["G"], "ci95": e.get("bootstrap_ci95")}
                                for m, d in pr["H5"]["gap_closed"][s].items() for ref, e in d.items()]
        c = pr["H5"]["cost"][s]
        rp = pr["H5"]["replay"]
        rows = []
        for m in order:
            cm = c.get(m) or {}
            pdc = cm.get("per_decision") or {}
            usd = cm.get("usd_per_decision", pdc.get("usd"))
            calls = cm.get("model_calls_per_decision", pdc.get("model_calls"))
            if m in rp["identity"]:
                rk = {"kind": "byte-identical replay", "rate": rp["identity"][m]["identical"] / max(rp["identity"][m]["checked"], 1)}
            elif m == "J":
                rk = {"kind": "regeneration agreement", "rate": rp["J_regeneration"]["agreement"]}
            elif m == "J_local" and rp["J_local_drift"]:
                rk = {"kind": "drift agreement (min over runs)",
                      "rate": min((d["agreement"] for d in rp["J_local_drift"] if d["agreement"] is not None), default=None)}
            elif m in ("RS", "CB-S"):
                rk = {"kind": "not measured", "rate": None}
            else:
                rk = {"kind": "deterministic (sealed labels / seeded ties)", "rate": 1.0}
            rows.append({"method": m, "usd_per_decision": usd, "model_calls_per_decision": calls,
                         "accuracy": pr["accuracy"][s]["decisive"].get(m), "replay": rk})
        fig["cost_vs_replay"][s] = rows
    return fig


def gate_analysis(dec_recs, elig_recs, ctx, selected_g):
    """Dev-informed configurations (FRAMING §3.4): NEI 0 and the verified-overturn gate.

    Per gated configuration, on decisive items: b / c against MAJ (random tie-break, as every
    other method) and against D, the reducer's own deterministic plurality default
    (`gate.default_winner`); F = items where some incorrect answer carries an accepted `supports`
    label; the harm property (GATE_SPEC.md) says every c_D item is an F item. Then the VV
    equivalence: item-level agreement of the gated decision with VV, with each disagreement
    classified."""
    out = {"note": ("dev_informed: NEI factor 0 and the verified-overturn gate were added after "
                    "inspecting dev c-cases (DEV_GATE §5.2); dev data provide no evidence for them."),
           "checks_checker_ids": sorted({e["checker"]["checker_id"] for e in ctx.checks.values()}),
           "accepted_checkers": ctx.accepted, "selected_gated": selected_g, "configs": {}}
    dec = [r["row"] for r in dec_recs]
    F_items = sorted(r["item"]["id"] for r in dec_recs
                     if any(supports_effective(v, ctx.accepted) and not v["correct"] for v in r["parsed"]))
    out["F"] = len(F_items)
    out["F_items"] = F_items
    out["decisive_majority_tied"] = sum(r["majority_tied"] for r in dec)
    for cfg in GATED_GRID:
        n = len(dec)
        stage = Counter()
        bD = cD = 0
        c_items, cD_items, disagree = [], [], []
        agree_obj = agree_correct = 0
        for rec in dec_recs:
            row, g = rec["row"], rec["grid"][cfg]
            gt = (g["sel"] or {}).get("gate")
            stage[gt["stage"] if gt else "no_slot"] += 1
            d_ok = int(rec["by_id"][gt["default_winner"]]["correct"]) if gt else row["MAJ"]
            if g["correct"] and not d_ok:
                bD += 1
            if d_ok and not g["correct"]:
                cD += 1
                cD_items.append(row["id"])
            if row["MAJ"] and not g["correct"]:
                c_items.append(row["id"])
            agree_obj += int(g["obj"] == row["VV_obj"])
            agree_correct += int(g["correct"] == row["VV"])
            if g["correct"] != row["VV"]:
                d_obj = rec["by_id"][gt["default_winner"]]["parsed"] if gt else None
                g_verified = bool(gt and gt["stage"] == "verified")
                vc = Counter(v["parsed"] for v in rec["parsed"] if supports_effective(v, ctx.accepted))
                vv_tied = bool(vc) and sum(1 for k in vc.values() if k == max(vc.values())) > 1
                if g_verified != (not row["VV_fallback"]):
                    why = "verified-set mismatch"
                elif not g_verified:
                    why = ("both fall back to plurality; D (policy tie-break) "
                           + ("!= MAJ (random tie-break)" if d_obj != row["MAJ_obj"] else "== MAJ"))
                else:
                    why = ("both verified; policy score vs VV headcount among verified values"
                           + ("; VV tie broken at random" if vv_tied else ""))
                disagree.append({"id": row["id"], "source": row["source"], "VV_obj": row["VV_obj"], "VV": row["VV"],
                                 "gated_obj": g["obj"], "gated": g["correct"], "MAJ_obj": row["MAJ_obj"],
                                 "D_obj": d_obj, "stage": gt["stage"] if gt else None, "why": why})
        ov = overturn(dec, "G:" + cfg)
        out["configs"][cfg] = {
            "b": ov["b"], "c": ov["c"], "b_minus_c": ov["b"] - ov["c"], "acc": sum(r["G:" + cfg] for r in dec) / n if n else None,
            "p_exact_mcnemar": mcnemar_p(ov["b"], ov["c"]), "q_r": ov["q_r"], "p_w": ov["p_w"],
            "b_vs_D": bD, "c_vs_D": cD, "c_vs_D_items": cD_items, "c_items": c_items,
            "harm_bound_holds": set(cD_items) <= set(F_items), "stage_counts": dict(stage),
            "VV_agreement_obj": agree_obj, "VV_agreement_correct": agree_correct, "VV_disagreements": disagree}
    return out


def h3(recs, elig_recs, ctx, replay_ok, be_wall):
    """Calls, tokens, dollars and wall time per item for BE (checks) and J; replay; J drift."""
    used = defaultdict(set)
    for rec in recs:
        for v in rec["parsed"]:
            for a in v["audit"]:
                if a.get("check"):
                    used[rec["item"]["id"]].add(a["check"])
    all_used = set().union(*used.values()) if used else set()
    present = [ctx.checks[k] for k in sorted(all_used) if k in ctx.checks]

    def tot(rows, k):
        vals = [r.get(k) for r in rows if r.get(k) is not None]
        return sum(vals) if vals else None
    n = len(recs) or 1
    jrows = list(ctx.judge.get(("J", 0), {}).values())
    regen = ctx.judge.get(("J", 1), {})
    agree = [int(r.get("selected") == ctx.judge[("J", 0)].get(i, {}).get("selected")) for i, r in regen.items()
             if i in ctx.judge.get(("J", 0), {})]
    return {
        "BE": {"distinct_checks": len(all_used), "checks_with_records": len(present),
               "checks_per_item": len(all_used) / n,
               "checker_cost_usd": tot(present, "cost_usd"), "checker_duration_ms": tot(present, "duration_ms"),
               "checker_input_tokens": tot(present, "input_tokens"), "checker_output_tokens": tot(present, "output_tokens"),
               "reducer_calls_per_item": 1, "reducer_wall_s_mean": sum(be_wall) / len(be_wall) if be_wall else None,
               "replay_identical": replay_ok, "replay_checked": len(elig_recs)},
        "J": {"calls": len(jrows), "calls_per_item": len(jrows) / n, "input_tokens": tot(jrows, "input_tokens"),
              "output_tokens": tot(jrows, "output_tokens"), "usd": tot(jrows, "usd"), "wall_ms": tot(jrows, "wall_ms"),
              "regeneration_items": len(agree),
              "regeneration_agreement": sum(agree) / len(agree) if agree else None},
    }


def selftest():
    assert mcnemar_p(0, 0) == 1.0
    assert abs(mcnemar_p(2, 8) - 0.109375) < 1e-12
    for a, b, c, d in [(1, 2, 8, 10), (12, 9, 2, 21), (0, 5, 0, 5), (40, 3, 3, 4)]:
        lo, hi = newcombe_paired(a, b, c, d)
        D = (b - c) / (a + b + c + d)
        assert lo <= D <= hi
        lo2, hi2 = newcombe_paired(a, c, b, d)
        assert abs(lo + hi2) < 1e-12 and abs(hi + lo2) < 1e-12
    assert [changed_fields(g) for g in GRID] == [0, 1, 1, 2, 1, 2]
    assert len(FULL_GRID) == 18 and len(DEV_INFORMED) == 12 and set(GRID) < set(FULL_GRID)
    # prereg statistics
    assert abs(cp_upper(0, 45) - (1 - 0.025 ** (1 / 45))) < 1e-9
    assert cp_upper(10, 373) < H3A_BOUND < cp_upper(11, 373)          # prereg §2.2: c <= 10 at n_R = 373
    h = holm({"H1a": 0.02, "H1b": 0.04})
    assert h["H1a"]["reject"] and h["H1b"]["reject"] and abs(h["H1a"]["p_holm"] - 0.04) < 1e-12
    h = holm({"H1a": 0.03, "H1b": 0.01})
    assert h["H1b"]["reject"] and h["H1a"]["reject"]
    assert not any(v["reject"] for v in holm({"H1a": 0.03, "H1b": 0.04}).values())
    for k, v in PREREG_TEMPLATES.items():
        cfg = None if k == "B0" else PREREG_CONFIGS["BE"] if k in ("BE", "EO") else PREREG_CONFIGS["BE-G"]
        assert template_sha("BE" if k in ("BE", "BE-G") else k, cfg, [PREREG_CHECKER]) == v, k
    print("evaluate_v5 selftest ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
