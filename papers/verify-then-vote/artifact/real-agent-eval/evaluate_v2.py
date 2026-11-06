#!/usr/bin/env python3
"""
Bran Real-Agent Evaluation Harness v2 — reviewer controls

Re-uses the v1 pipeline (evaluate_v1.py, a verbatim copy of the original
evaluate.py) and adds:

  1. A stricter ground-truth grader (subject AND object AND predicate
     compatibility AND polarity agreement), reported side by side with v1.
  2. Matched controls on the identical eligible conflict set:
       majority vote, Bran (citation association ON / OFF), Bran over sealed
       artifacts, evidence-only argmax (unsealed / sealed), majority (sealed),
       plus Bran with the recency weight zeroed (diagnostic).
  3. A per-conflict paired decision table   -> results/paired_decisions.csv
  4. Exact McNemar test (Bran vs majority) and a question-clustered bootstrap
     95% CI on the accuracy difference.
  5. Independently measured separation margins -> results/separation_margins.csv
  6. A precision adjudication sheet           -> results/precision_adjudication.csv

Usage:
    python3 evaluate_v2.py
    python3 evaluate_v2.py --bootstrap 10000 --seed 42
"""

import copy
import csv
import hashlib
import json
import math
import random
import re
import argparse
from collections import Counter, defaultdict
from pathlib import Path

import evaluate_v1 as v1

HERE = Path(__file__).parent
RESULTS_DIR = HERE / "results"
DEADBAND = 0.05  # compiler.rs:84 deadband_threshold = 500 / 10,000


def quantize(x):
    """compiler.rs:75 quantize(): round(score * 10,000) as integer."""
    return int(round(x * 10000))


DEADBAND_Q = quantize(DEADBAND)


# ── Pipeline (identical to v1.evaluate_question, but non-mutating) ──

_TRUNCATED = re.compile(r'\b(a|an|the|of|to|in|by|for|with|from)\s*$')


def load_contributions(responses, associate=True):
    """Build the contribution list exactly as v1.evaluate_question does
    (evaluate_v1.py:339-353), on a deep copy so runs cannot contaminate
    each other. `associate=False` skips context-aware evidence association."""
    responses = copy.deepcopy(responses)
    contributions = []
    for resp in responses:
        agent_claims = []
        for claim in resp.get("claims", []):
            if _TRUNCATED.search(claim.get("object", "").strip()):
                continue
            claim["agent"] = resp.get("agent", "unknown")
            claim["calibration"] = resp.get("calibration", 0.7)
            agent_claims.append(claim)
        if associate:
            v1.enrich_evidence_from_context(agent_claims, resp.get("raw_response", ""))
        contributions.extend(agent_claims)
    return contributions


def seal(contributions):
    """Serialize canonically (sorted keys, compact separators), SHA-256 it,
    and reload. Returns (reloaded_contributions, hex_digest)."""
    blob = json.dumps(contributions, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(blob).hexdigest()
    return json.loads(blob.decode("utf-8")), digest


# ── Reducers: each returns the winning member INDEX within a conflict set ──

def bran_idx(members, weights=None):
    """Same argmax as v1.bran_select (stable sort, first wins ties)."""
    if weights is None:
        scores = [v1.score_contribution(m, len(members), i) for i, m in enumerate(members)]
    else:
        saved = dict(v1.WEIGHTS)
        v1.WEIGHTS.update(weights)
        try:
            scores = [v1.score_contribution(m, len(members), i) for i, m in enumerate(members)]
        finally:
            v1.WEIGHTS.clear()
            v1.WEIGHTS.update(saved)
    order = sorted(range(len(members)), key=lambda i: -scores[i])
    return order[0]


def majority_idx(members):
    """Same as v1.majority_vote_select: most frequent object, first member of
    that object group; ties broken by first-seen object (dict order)."""
    obj_counts = defaultdict(list)
    for i, m in enumerate(members):
        obj_counts[m.get("object", "").lower().strip()].append(i)
    best_obj = max(obj_counts, key=lambda k: len(obj_counts[k]))
    return obj_counts[best_obj][0]


def evidence_only_idx(members):
    """argmax of v1.score_evidence; first member wins ties."""
    evs = [v1.score_evidence(m.get("evidence", [])) for m in members]
    return max(range(len(members)), key=lambda i: (evs[i], -i))


# ── v2 grader ──

_STOPS = {"a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
          "has", "have", "had", "do", "does", "did", "in", "on", "at", "to",
          "for", "of", "with", "by", "from", "as", "it", "its", "that", "this",
          "and", "or", "but", "can", "will", "just", "about", "than", "also",
          "so", "very", "more", "most", "some", "any", "all", "both", "may",
          "might", "could", "would", "should", "which", "who", "their", "there"}

# Negation cues. "n't" contractions are rewritten to " not" before tokenizing.
_NEG_CUES = {"not", "no", "never", "cannot", "none", "neither", "nor",
             "nothing", "ineffective", "lack", "lacks"}

# Discourse answer markers stripped from the front of subjects ("No, glass ...")
_DISCOURSE = re.compile(r'^(?:claim\s*:\s*|no\s*,\s*|yes\s*,\s*)+', re.I)

# Unresolved anaphora / expletives: a triple whose subject is one of these does
# not, by itself, assert anything about a named entity.
_PRONOUNS = {"it", "this", "that", "these", "those", "they", "there", "he", "she"}

# Small surface-form alias table applied before tokenizing (both sides).
_ALIASES = [
    (re.compile(r'(?<=\d),(?=\d{3})'), ""),             # 299,792,458 -> 299792458
    (re.compile(r'\bm/s\b'), " meters per second "),
    (re.compile(r'\bkm\b'), " kilometers "),
    (re.compile(r"n't\b"), " not"),
]

# Predicate synonym groups: name -> trigger PREFIXES (matched with startswith
# against claim tokens). A GT predicate is mapped to every group one of whose
# key words occurs in it; a claim is predicate-compatible if any trigger of
# any mapped group occurs in its relation span (predicate field, subject
# field, and first 4 tokens of the matching object clause).
PREDICATE_GROUPS = {
    "copula":     ({"is", "are", "was", "were", "means", "classified"},
                   ["is", "are", "was", "were", "be", "remain", "consider", "classif",
                    "reclassif", "regard", "known", "defin", "call", "categor", "mean"]),
    "cause":      ({"cause", "caused", "causes", "contributes", "originated", "exaggerated"},
                   ["caus", "lead", "result", "trigger", "contribut", "link", "originat",
                    "stem", "exaggerat", "induc"]),
    "have":       ({"have", "has", "include", "lacks"},
                   ["have", "has", "contain", "consist", "possess", "includ", "compris",
                    "lack", "made"]),
    "capital":    ({"capital"}, ["capital"]),
    "speed":      ({"speed"}, ["speed", "travel", "velocit"]),
    "distance":   ({"distance"}, ["distanc", "away", "astronomical"]),
    "create":     ({"created", "invented"},
                   ["creat", "invent", "develop", "design", "found", "credit", "author"]),
    "stimulate":  ({"stimulate"},
                   ["stimul", "train", "activat", "prompt", "induc", "trigger", "teach"]),
    "account":    ({"accounts", "makes"},
                   ["account", "make", "compris", "constitut", "represent"]),
    "detect":     ({"detected", "detection"},
                   ["detect", "infer", "observ", "measur", "evidence"]),
    "describe":   ({"described"}, ["describ", "explain", "result", "curvatur", "model"]),
    "work_on":    ({"work", "target"},
                   ["work", "effective", "ineffective", "target", "treat", "kill", "act"]),
    "useful":     ({"excel", "useful", "advantage", "benefit", "strong", "better",
                    "recommended", "overkill"},
                   ["excel", "useful", "good", "important", "ideal", "suit", "simulat",
                    "advantag", "benefit", "strong", "better", "recommend", "overkill", "help"]),
    "purpose":    ({"purpose", "allows"}, ["allow", "permit", "enabl", "purpose", "let"]),
    "memory":     ({"memory"}, ["memor", "remember", "recall"]),
    "prevent":    ({"prevent", "prevented", "reduce"},
                   ["prevent", "protect", "reduc", "mitigat", "stop"]),
    "uses":       ({"use", "uses", "implements", "operates", "ensures"},
                   ["use", "implement", "operat", "rely", "employ", "ensur", "via"]),
}


def _clean(text):
    text = text.lower()
    text = re.sub(r'\*+', '', text)
    for pat, rep in _ALIASES:
        text = pat.sub(rep, text)
    return text


def _stem(tok):
    if len(tok) > 5 and tok.endswith("ing"):
        return tok[:-3]
    if len(tok) > 5 and tok.endswith("ed") and not tok.endswith("eed"):
        return tok[:-2]
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


def _words(text):
    """Ordered raw content words (unstemmed), stopwords and negation removed."""
    raw = re.findall(r'[a-z0-9]+', _clean(text))
    return [t for t in raw if t not in _STOPS and t not in _NEG_CUES]


def _toks(text):
    """Ordered content tokens (stemmed)."""
    return [_stem(t) for t in _words(text)]


def _neg_count(text):
    return sum(1 for t in re.findall(r'[a-z]+', _clean(text)) if t in _NEG_CUES)


def _strip_subject(subj):
    s = re.sub(r'\*+', '', subj).strip()
    if ":" in s:               # "**Cognitive function:** Caffeine in coffee can"
        s = s.rsplit(":", 1)[1].strip()
    return _DISCOURSE.sub("", s).strip()


def _split_clauses(obj):
    """Split a claim object into clauses at ; / ' but ' / ', not|which|while|it|they'."""
    parts = re.split(r';|\s—\s|\s+but\s+|,\s*(?=(?:not|which|while|whereas|it|they)\b)', obj)
    return [p.strip() for p in parts if p.strip()]


def _gt_groups(gp):
    words = set(gp.lower().replace("_", " ").split())
    return [g for g, (keys, _) in PREDICATE_GROUPS.items() if keys & words]


def _predicate_ok(gp, relation_words):
    groups = _gt_groups(gp)
    if groups:
        triggers = [t for g in groups for t in PREDICATE_GROUPS[g][1]]
    else:   # fallback: GT predicate's own content words as 5-char prefixes
        triggers = [w[:5] for w in _words(gp.replace("_", " "))]
    if not triggers:
        return True
    return any(w.startswith(tr) for w in relation_words for tr in triggers)


def _tok_eq(a, b):
    """Token equality with a conservative prefix allowance (pseudonym ~ pseudonymous)."""
    if a == b:
        return True
    return (a.isalpha() and b.isalpha() and min(len(a), len(b)) >= 5
            and (a.startswith(b) or b.startswith(a)))


def _frac(gt_tokens, have_tokens):
    if not gt_tokens:
        return 1.0
    return sum(1 for t in gt_tokens if any(_tok_eq(t, h) for h in have_tokens)) / len(gt_tokens)


SUBJ_THRESHOLD = 0.5   # share of GT subject tokens that must appear in claim subject
OBJ_THRESHOLD = 0.6    # share of GT object tokens that must appear in one object clause

_STAGES = ["subject_unresolved", "subject", "object", "predicate", "polarity", "match"]


def match_v2_detail(claim, gt_triple):
    """Return (matched, reason). Reason is the furthest stage reached:
    subject_unresolved < subject < object < predicate < polarity < match."""
    gs, gp, go = gt_triple
    subj = _strip_subject(claim.get("subject", ""))
    pred = claim.get("predicate", "")
    obj = claim.get("object", "")

    subj_words = re.findall(r'[a-z]+', subj.lower())
    if not subj_words or (len(subj_words) == 1 and subj_words[0] in _PRONOUNS):
        return False, "subject_unresolved"

    subj_toks = _toks(subj)
    gs_t, go_t = _toks(gs), _toks(go)
    gt_neg = (_neg_count(gp.replace("_", " ")) + _neg_count(go)) % 2

    # Orientation: as given, plus swapped for copular GT ("Pacific Ocean is
    # largest ocean" vs claim "The largest ocean is the Pacific Ocean").
    orientations = [(gs_t, go_t)]
    if "copula" in _gt_groups(gp):
        orientations.append((go_t, gs_t))

    clauses = _split_clauses(obj) or [obj]
    # Negation cues in the predicate field and the subject scope over the
    # first clause only; later clauses carry only their own cues.
    head_neg = _neg_count(pred) + _neg_count(subj)
    # Relation span: predicate field + subject words + the words of the first
    # clause that precede its first object token (the elided verb is carried
    # over to later clauses: "effective against bacteria, not viruses").
    head_rel = _words(pred) + re.findall(r'[a-z]+', _clean(pred)) + _words(subj)

    best = 1
    for s_t, o_t in orientations:
        if _frac(s_t, subj_toks) < SUBJ_THRESHOLD:
            continue
        best = max(best, 2)
        carried = []
        for ci, clause in enumerate(clauses):
            c_words = _words(clause)
            c_toks = [_stem(w) for w in c_words]
            first_obj = next((i for i, t in enumerate(c_toks)
                              if any(_tok_eq(t, g) for g in o_t)), len(c_toks))
            pre_obj = c_words[:max(first_obj, 1)]
            if ci == 0:
                carried = pre_obj
            if _frac(o_t, c_toks) < OBJ_THRESHOLD:
                continue
            best = max(best, 3)
            relation = head_rel + carried + pre_obj + re.findall(r'[a-z]+', _clean(clause))[:5]
            if not _predicate_ok(gp, relation):
                continue
            best = max(best, 4)
            neg = (_neg_count(clause) + (head_neg if ci == 0 else 0)) % 2
            if neg != gt_neg:
                continue
            return True, "match"
    return False, _STAGES[best]


def match_v2(claim, gt_triple):
    return match_v2_detail(claim, gt_triple)[0]


GRADERS = {"v1": v1.claim_matches_gt, "v2": match_v2}


# ── Per-question evaluation ──

def correct_any(claim, gt, grader):
    return any(grader(claim, g) for g in gt)


def run_question(q, responses):
    """Return conflict-level rows and precision/recall data for every grader."""
    gt = [tuple(x) for x in q["ground_truth"]]

    on = load_contributions(responses, associate=True)
    off = load_contributions(responses, associate=False)
    sealed, digest = seal(on)

    cs_on = v1.detect_conflicts(on)
    cs_off = v1.detect_conflicts(off)
    cs_sealed = v1.detect_conflicts(sealed)
    assert [c["key"] for c in cs_on] == [c["key"] for c in cs_off] == [c["key"] for c in cs_sealed]

    conflicts = []
    for k, (a, b, s) in enumerate(zip(cs_on, cs_off, cs_sealed)):
        members = a["members"]
        sel = {
            "bran": bran_idx(members),
            "majority": majority_idx(members),
            "bran_assoc_on": bran_idx(members),
            "bran_assoc_off": bran_idx(b["members"]),
            "bran_sealed": bran_idx(s["members"]),
            "evidence_only": evidence_only_idx(members),
            "evidence_only_sealed": evidence_only_idx(s["members"]),
            "majority_sealed": majority_idx(s["members"]),
            "bran_no_recency": bran_idx(members, {"recency": 0.0}),
            "first_member": 0,
            "last_member": len(members) - 1,
        }
        conflicts.append({"q": q, "key": a["key"], "type": a["type"],
                          "members": members, "members_off": b["members"], "sel": sel})
    return {"q": q, "gt": gt, "conflicts": conflicts, "digest": digest,
            "contributions": on}


def prec_recall(run, grader, method="bran"):
    gt = run["gt"]
    winners = [c["members"][c["sel"][method]] for c in run["conflicts"]]
    tp = sum(1 for w in winners if correct_any(w, gt, grader))
    fp = len(winners) - tp
    matched = {i for i, g in enumerate(gt) if any(grader(w, g) for w in winners)}
    return tp, fp, len(gt) - len(matched), (tp / len(winners) if winners else 0.0), \
        (len(matched) / len(gt) if gt else 0.0)


# ── Statistics ──

def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def cluster_bootstrap(rows, a_key, b_key, n_boot, seed):
    by_q = defaultdict(list)
    for r in rows:
        by_q[r["question"]].append(r)
    qids = sorted(by_q)
    rng = random.Random(seed)
    diffs = []
    for _ in range(n_boot):
        sample = [rng.choice(qids) for _ in qids]
        n = sum(len(by_q[x]) for x in sample)
        d = sum(r[a_key] - r[b_key] for x in sample for r in by_q[x])
        diffs.append(d / n)
    diffs.sort()
    lo = diffs[int(0.025 * n_boot)]
    hi = diffs[min(n_boot - 1, int(0.975 * n_boot))]
    point = sum(r[a_key] - r[b_key] for r in rows) / len(rows)
    return point, lo, hi, len(qids)


# ── Main ──

CONTROL_COLS = ["bran", "majority", "bran_assoc_on", "bran_assoc_off", "bran_sealed",
                "evidence_only", "evidence_only_sealed", "majority_sealed",
                "bran_no_recency", "first_member", "last_member"]


def eligible_rows(runs, grader_name):
    grader = GRADERS[grader_name]
    rows = []
    for run in runs:
        gt = run["gt"]
        for cs in run["conflicts"]:
            if cs["type"] != "contradiction":
                continue
            flags = [correct_any(m, gt, grader) for m in cs["members"]]
            if not any(flags):
                continue
            row = {"question": run["q"]["id"], "category": run["q"]["category"],
                   "subject": cs["key"][0], "predicate": cs["key"][1],
                   "n_members": len(cs["members"]),
                   "n_agents": len({m["agent"] for m in cs["members"]}),
                   "n_correct_members": sum(flags),
                   "decisive": int(not all(flags))}
            for col in CONTROL_COLS:
                row[col] = int(flags[cs["sel"][col]])
            row["sel"] = dict(cs["sel"])
            row["_cs"] = cs
            row["_flags"] = flags
            rows.append(row)
    return rows


def margins(row):
    cs, flags = row["_cs"], row["_flags"]
    members = cs["members"]
    ev = [v1.score_evidence(m.get("evidence", [])) for m in members]
    S = [v1.score_contribution(m, len(members), i) for i, m in enumerate(members)]
    corr = [i for i, f in enumerate(flags) if f]
    inc = [i for i, f in enumerate(flags) if not f]
    out = {"question": row["question"], "predicate": row["predicate"],
           "subject": row["subject"], "n_members": len(members),
           "n_correct": len(corr), "n_incorrect": len(inc),
           "bran_correct": row["bran"]}
    if not inc:
        out.update(ev_gap="", score_gap="", ev_separated="n/a", score_separated="n/a")
        return out
    evg = min(ev[i] for i in corr) - max(ev[i] for i in inc)
    sg = min(S[i] for i in corr) - max(S[i] for i in inc)
    sq = sorted((quantize(x) for x in S), reverse=True)
    # Separation and deadband are judged on integer-quantized values, as in
    # compiler.rs:459-466 (gap < 500 enters the deadband).
    out.update(ev_gap=round(evg, 6), score_gap=round(sg, 6),
               ev_separated=int(quantize(evg) > DEADBAND_Q),
               score_separated=int(quantize(sg) > DEADBAND_Q),
               top2_score_gap=round((sq[0] - sq[1]) / 10000, 6),
               in_rust_deadband=int(sq[0] - sq[1] < DEADBAND_Q))
    return out


def adjudication_category(claim, gt):
    """HEURISTIC guess only — not an adjudicated label."""
    subj = _strip_subject(claim.get("subject", ""))
    words = re.findall(r'[a-z]+', subj.lower())
    obj_t = _toks(claim.get("object", ""))
    raw_subj = claim.get("subject", "")
    if (not words or words[0] in _PRONOUNS or len(words) > 8
            or len(obj_t) < 2 or re.search(r'[:(\[]\s*$', claim.get("object", ""))
            or re.match(r'^\s*(\*\*|#|\d+\.)', raw_subj) and ":" in raw_subj):
        return "extraction-garbage"
    # same subject+object+predicate as a gold triple but opposite polarity -> contradicts gold
    reasons = [match_v2_detail(claim, g)[1] for g in gt]
    if "polarity" in reasons:
        return "incorrect"
    # lenient v1 grader accepted it, or only the predicate table rejected it
    if correct_any(claim, gt, v1.claim_matches_gt) or "predicate" in reasons:
        return "grader-miss"
    return "extra-but-true"


def nearest_gold(claim, gt):
    ct = set(_toks(" ".join([claim.get("subject", ""), claim.get("predicate", ""),
                             claim.get("object", "")])))
    best, best_j = None, -1.0
    for g in gt:
        gtk = set(_toks(" ".join([g[0], g[1].replace("_", " "), g[2]])))
        j = len(ct & gtk) / len(ct | gtk) if (ct | gtk) else 0.0
        if j > best_j:
            best, best_j = g, j
    return best, best_j


def write_csv(path, rows, cols):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def pct(a, b):
    return f"{a}/{b}={a / b:.4f}" if b else "n/a"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bootstrap", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    questions = json.load(open(HERE / "questions.json"))
    runs = []
    for q in questions:
        f = RESULTS_DIR / f"{q['id']}.json"
        if not f.exists():
            continue
        responses = json.load(open(f))
        if responses:
            runs.append(run_question(q, responses))

    print(f"Questions evaluated: {len(runs)}")
    print("Category counts:", dict(Counter(q["category"] for q in questions)))

    # Sanity: v2 pipeline reproduces v1 numbers with the v1 grader
    tp = sum(prec_recall(r, v1.claim_matches_gt)[0] for r in runs)
    print(f"Sanity (v1 grader, bran TP summed): {tp}")

    summary = {"questions_evaluated": len(runs), "graders": {},
               "artifact_digests": {r["q"]["id"]: r["digest"] for r in runs}}

    # Sealing check: selections identical sealed vs unsealed, all conflict sets
    n_sets = sum(len(r["conflicts"]) for r in runs)
    diff_bran = sum(1 for r in runs for c in r["conflicts"] if c["sel"]["bran"] != c["sel"]["bran_sealed"])
    diff_ev = sum(1 for r in runs for c in r["conflicts"]
                  if c["sel"]["evidence_only"] != c["sel"]["evidence_only_sealed"])
    diff_maj = sum(1 for r in runs for c in r["conflicts"] if c["sel"]["majority"] != c["sel"]["majority_sealed"])
    diff_assoc = sum(1 for r in runs for c in r["conflicts"] if c["sel"]["bran_assoc_on"] != c["sel"]["bran_assoc_off"])
    print(f"\nSealing: {n_sets} conflict sets (all types); selection differences sealed vs unsealed: "
          f"bran={diff_bran} evidence_only={diff_ev} majority={diff_maj}")
    print(f"Citation association ON vs OFF changes Bran's selection in {diff_assoc}/{n_sets} sets")
    summary["sealing"] = {"conflict_sets": n_sets, "bran_diffs": diff_bran,
                          "evidence_only_diffs": diff_ev, "majority_diffs": diff_maj,
                          "assoc_on_vs_off_diffs_all_sets": diff_assoc}

    # Precision / recall, v1 vs v2 grader
    print(f"\n{'Method':<16} {'grader':<6} {'TP':>5} {'FP':>5} {'FN':>5} {'macroP':>8} {'macroR':>8}")
    for method in ["bran", "majority", "bran_assoc_off", "evidence_only", "last_member", "first_member"]:
        for gname, grader in GRADERS.items():
            agg = [prec_recall(r, grader, method) for r in runs]
            T, F, N = (sum(a[i] for a in agg) for i in range(3))
            mp = sum(a[3] for a in agg) / len(agg)
            mr = sum(a[4] for a in agg) / len(agg)
            print(f"{method:<16} {gname:<6} {T:>5} {F:>5} {N:>5} {mp:>8.4f} {mr:>8.4f}")
            summary["graders"].setdefault(gname, {}).setdefault("prf", {})[method] = {
                "tp": T, "fp": F, "fn": N, "macro_precision": round(mp, 6), "macro_recall": round(mr, 6)}

    for gname in GRADERS:
        rows = eligible_rows(runs, gname)
        n = len(rows)
        qs = sorted({r["question"] for r in rows})
        dec = [r for r in rows if r["decisive"]]
        print(f"\n=== Grader {gname}: {n} eligible conflicts from {len(qs)} questions "
              f"({len(dec)} decisive, {n - len(dec)} where every member matches GT) ===")
        print("  questions:", ", ".join(qs))
        g = summary["graders"][gname]
        g["eligible"] = n
        g["eligible_questions"] = qs
        g["decisive"] = len(dec)
        g["accuracy"] = {}
        for col in CONTROL_COLS:
            k = sum(r[col] for r in rows)
            kd = sum(r[col] for r in dec)
            print(f"  {col:<22} all: {pct(k, n):<16} decisive-only: {pct(kd, len(dec))}")
            g["accuracy"][col] = {"correct": k, "total": n, "decisive_correct": kd,
                                  "decisive_total": len(dec)}

        b = sum(1 for r in rows if r["bran"] and not r["majority"])
        c = sum(1 for r in rows if r["majority"] and not r["bran"])
        p = mcnemar_exact(b, c)
        point, lo, hi, nq = cluster_bootstrap(rows, "bran", "majority", args.bootstrap, args.seed)
        print(f"  McNemar exact (Bran vs majority): b(Bran only)={b} c(majority only)={c} p={p:.6f}")
        print(f"  Clustered bootstrap ({args.bootstrap} resamples over {nq} questions, seed {args.seed}): "
              f"diff={point:.4f} 95% CI [{lo:.4f}, {hi:.4f}]")
        g["mcnemar"] = {"b_bran_only": b, "c_majority_only": c, "p_exact": p}
        g["cluster_bootstrap"] = {"diff": point, "ci95": [lo, hi], "n_questions": nq,
                                  "resamples": args.bootstrap, "seed": args.seed}
        # Bran vs no-recency and vs last_member, for context
        for other in ["bran_no_recency", "last_member", "evidence_only"]:
            bb = sum(1 for r in rows if r["bran"] and not r[other])
            cc = sum(1 for r in rows if r[other] and not r["bran"])
            print(f"  Bran vs {other}: discordant b={bb} c={cc} p={mcnemar_exact(bb, cc):.6f}")

        # Paired decision table + margins
        suffix = "" if gname == "v2" else "_v1grader"
        write_csv(RESULTS_DIR / f"paired_decisions{suffix}.csv", rows,
                  ["question", "category", "subject", "predicate", "n_members", "n_agents",
                   "n_correct_members", "decisive"] + CONTROL_COLS)
        mrows = [margins(r) for r in rows]
        write_csv(RESULTS_DIR / f"separation_margins{suffix}.csv", mrows,
                  ["question", "subject", "predicate", "n_members", "n_correct", "n_incorrect",
                   "bran_correct", "ev_gap", "ev_separated", "score_gap", "score_separated",
                   "top2_score_gap", "in_rust_deadband"])
        dm = [m for m in mrows if m["ev_separated"] != "n/a"]
        g["margins"] = {}
        for key in ["ev_separated", "score_separated"]:
            tab = Counter((m[key], m["bran_correct"]) for m in dm)
            print(f"  {key} (>{DEADBAND}) over {len(dm)} decisive: separated={sum(m[key] for m in dm)}; "
                  f"crosstab (separated,bran_correct): "
                  f"{{(1,1):{tab[(1, 1)]}, (1,0):{tab[(1, 0)]}, (0,1):{tab[(0, 1)]}, (0,0):{tab[(0, 0)]}}}")
            g["margins"][key] = {"decisive": len(dm), "separated": sum(m[key] for m in dm),
                                 "sep_correct": tab[(1, 1)], "sep_wrong": tab[(1, 0)],
                                 "nosep_correct": tab[(0, 1)], "nosep_wrong": tab[(0, 0)]}
        pos = [m for m in dm if m["ev_gap"] > 0]
        print(f"  ev_gap > 0 (any positive separation): {len(pos)}/{len(dm)}")
        idb = sum(m["in_rust_deadband"] for m in dm)
        idb_all = sum(1 for r in rows if (lambda S: S[0] - S[1] < DEADBAND_Q)(
            sorted([quantize(v1.score_contribution(m, len(r["_cs"]["members"]), i))
                    for i, m in enumerate(r["_cs"]["members"])], reverse=True)))
        print(f"  top-2 Bran score gap < {DEADBAND} (would enter Rust deadband/Schulze): "
              f"{idb}/{len(dm)} decisive, {idb_all}/{n} eligible")
        g["margins"]["top2_in_deadband_decisive"] = idb
        g["margins"]["top2_in_deadband_eligible"] = idb_all

    # Precision adjudication sheet (v2 grader, Bran winners marked wrong)
    adj = []
    for r in runs:
        gt = r["gt"]
        for cs in r["conflicts"]:
            w = cs["members"][cs["sel"]["bran"]]
            if correct_any(w, gt, match_v2):
                continue
            ng, j = nearest_gold(w, gt)
            adj.append({"question": r["q"]["id"],
                        "claim_text": w.get("raw_sentence", ""),
                        "triple": f"({w.get('subject', '')} | {w.get('predicate', '')} | {w.get('object', '')})",
                        "nearest_gold_triple": f"({ng[0]} | {ng[1]} | {ng[2]})",
                        "nearest_jaccard": round(j, 4),
                        "v1_grader_match": int(correct_any(w, gt, v1.claim_matches_gt)),
                        "auto_category_heuristic": adjudication_category(w, gt),
                        "human_label": ""})
    write_csv(RESULTS_DIR / "precision_adjudication.csv", adj,
              ["question", "claim_text", "triple", "nearest_gold_triple", "nearest_jaccard",
               "v1_grader_match", "auto_category_heuristic", "human_label"])
    dist = Counter(a["auto_category_heuristic"] for a in adj)
    print(f"\nPrecision adjudication sheet: {len(adj)} Bran winners marked wrong by v2 grader")
    print("  HEURISTIC auto-category distribution (NOT adjudicated):", dict(dist))
    summary["precision_adjudication"] = {"rows": len(adj), "heuristic_distribution": dict(dist)}

    with open(RESULTS_DIR / "evaluation_v2.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nWrote {RESULTS_DIR / 'evaluation_v2.json'}")


if __name__ == "__main__":
    main()
