#!/usr/bin/env python3
"""
Bran Real-Agent Evaluation Harness v2

Evaluates Bran's conflict resolution quality against 4 baselines using
real Ollama LLM agent outputs. Three metrics:

1. Recall: fraction of ground-truth triples recovered by any winning claim
2. Conflict Resolution Accuracy: when agents disagree and one side aligns
   with GT, did the method pick the correct side?
3. Precision: fraction of winning claims that match some GT triple

Usage:
    python3 evaluate.py
    python3 evaluate.py --verbose
    python3 evaluate.py --bootstrap 2000
"""

import json
import sys
import re
import random
import hashlib
import argparse
from collections import defaultdict
from pathlib import Path

# ── Bran scoring parameters (default weights from paper §6.6.1) ──

WEIGHTS = {
    "evidence": 0.35,
    "confidence": 0.20,
    "critique_survival": 0.25,
    "recency": 0.05,
    "constraint_alignment": 0.15,
}

EVIDENCE_TYPE_WEIGHTS = {
    "TOOL_RESULT": 1.0,
    "EMPIRICAL": 0.9,
    "CITATION": 0.8,
    "AUTHORITY": 0.5,
    "REASONING": 0.3,
}

LOWERING_FACTORS = {
    "HIGH": 1.0,
    "MEDIUM": 0.85,
    "LOW": 0.5,
}


# ── Evidence scoring ──

def score_evidence(evidence_list):
    total = 0.0
    for ev in evidence_list:
        tw = EVIDENCE_TYPE_WEIGHTS.get(ev.get("type", "REASONING"), 0.3)
        w = ev.get("weight", 0.7)
        sq = 0.8 if ev.get("type") in ("CITATION", "EMPIRICAL") else 1.0
        total += w * tw * sq
    return min(1.0, total)


# ── Composite scoring ──

def score_contribution(contrib, conflict_set_size, rank_in_set):
    ev = score_evidence(contrib.get("evidence", []))
    conf = contrib.get("confidence", 0.5) * contrib.get("calibration", 0.7)
    conf = max(0.0, min(1.0, conf))
    cs = 1.0
    rec = rank_in_set / max(1, conflict_set_size - 1) if conflict_set_size > 1 else 0.0
    ca = contrib.get("constraint_alignment", 1.0)
    S = (WEIGHTS["evidence"] * ev +
         WEIGHTS["confidence"] * conf +
         WEIGHTS["critique_survival"] * cs +
         WEIGHTS["recency"] * rec +
         WEIGHTS["constraint_alignment"] * ca)
    lf = LOWERING_FACTORS.get(contrib.get("lowering_confidence", "HIGH"), 1.0)
    return lf * S


# ── Context-aware evidence association (P2 lowering enrichment) ──

# Source detection patterns
_SOURCE_PATTERNS = [
    (re.compile(r'\b(NASA|IAU|WHO|CDC|FDA|NIH|ACS|IEEE|IETF|EPA)\b'), "AUTHORITY", 0.7),
    (re.compile(r'\b(Smithsonian|Britannica|Encyclopedia|National (?:Academy|Museum|Institute))\b'), "AUTHORITY", 0.7),
    (re.compile(r'\b(University of \w+)\b'), "EMPIRICAL", 0.75),
    (re.compile(r'(?:et al\.?,?\s*\d{4}|[A-Z][a-z]+,?\s*\d{4}\b)'), "CITATION", 0.8),
    (re.compile(r'\bhttps?://\S+'), "CITATION", 0.75),
    (re.compile(r'\[(\d+)\]'), "CITATION", 0.7),
    (re.compile(r'(?:according to|study|studies|research\b|found that)', re.I), "EMPIRICAL", 0.65),
]


def _is_source_line(text):
    """Check if a sentence is a source/citation line (not a factual assertion)."""
    text = text.strip()
    # Explicit source labels
    if re.match(r'^(?:Source|Reference|Cited?|See also)\s*:', text, re.I):
        return True
    # Numbered reference lines: "(1) Author..." or "[1] Author..."
    if re.match(r'^[\(\[]\d+[\)\]]\s+[A-Z]', text):
        return True
    # Lines that are just URLs
    if re.match(r'^https?://\S+$', text.strip()):
        return True
    # "Confidence level:" lines (metadata, not assertion)
    if re.match(r'^Confidence\s*(level)?\s*:', text, re.I):
        return True
    return False


def enrich_evidence_from_context(claims, raw_response):
    """Associate explicit source/citation lines with the claims they follow.

    Scans the raw response for source lines (labeled "Source:", numbered
    references, URLs) and associates them with the nearest preceding claim.
    Only enriches claims that currently have REASONING-only evidence.
    """
    if not raw_response:
        return

    # Split raw response into sentences
    sentences = re.split(r'(?<=[.!?])\s+', raw_response.strip())

    for claim in claims:
        raw_sent = claim.get("raw_sentence", "")
        if not raw_sent:
            continue

        # Find this claim's position in the sentence list
        claim_idx = None
        for i, sent in enumerate(sentences):
            if raw_sent[:40] in sent or sent[:40] in raw_sent:
                claim_idx = i
                break
        if claim_idx is None:
            continue

        # Look at the 1-3 sentences following the claim for source lines
        best_type = None
        best_weight = 0.0
        for offset in range(1, 4):
            next_idx = claim_idx + offset
            if next_idx >= len(sentences):
                break
            next_sent = sentences[next_idx]

            # Only use source/citation lines, not factual assertions
            if not _is_source_line(next_sent):
                # Stop scanning if we hit another assertion (source block ended)
                if offset > 1:
                    break
                continue

            # Check what type of source it is
            for pattern, ev_type, ev_weight in _SOURCE_PATTERNS:
                if pattern.search(next_sent):
                    if ev_weight > best_weight:
                        best_type = ev_type
                        best_weight = ev_weight

        # Only enrich if we found something better than what's already there
        existing_types = {e.get("type") for e in claim.get("evidence", [])}
        if best_type and best_type not in existing_types:
            if existing_types <= {"REASONING"}:
                claim["evidence"].append({
                    "type": best_type,
                    "weight": best_weight,
                    "text": "context-associated",
                })


# ── Conflict detection ──

def conflict_key(contrib):
    s = contrib.get("subject", "").lower().strip()
    p = contrib.get("predicate", "").lower().strip()
    return (s, p)


def detect_conflicts(contributions):
    groups = defaultdict(list)
    for c in contributions:
        key = conflict_key(c)
        groups[key].append(c)

    conflict_sets = []
    for key, members in groups.items():
        objects = set(m.get("object", "").lower().strip() for m in members)
        ctype = "redundancy" if len(objects) == 1 else "contradiction"
        conflict_sets.append({
            "key": key,
            "type": ctype,
            "members": members,
        })
    return conflict_sets


# ── Selection strategies ──

def bran_select(conflict_sets, **kwargs):
    winners = []
    for cs in conflict_sets:
        members = cs["members"]
        scored = [(score_contribution(m, len(members), i), m) for i, m in enumerate(members)]
        scored.sort(key=lambda x: -x[0])
        winners.append(scored[0][1])
    return winners


def majority_vote_select(conflict_sets, **kwargs):
    winners = []
    for cs in conflict_sets:
        members = cs["members"]
        obj_counts = defaultdict(list)
        for m in members:
            obj_counts[m.get("object", "").lower().strip()].append(m)
        best_obj = max(obj_counts, key=lambda k: len(obj_counts[k]))
        winners.append(obj_counts[best_obj][0])
    return winners


def best_confidence_select(conflict_sets, **kwargs):
    winners = []
    for cs in conflict_sets:
        winners.append(max(cs["members"], key=lambda m: m.get("confidence", 0.5)))
    return winners


def last_writer_wins_select(conflict_sets, **kwargs):
    return [cs["members"][-1] for cs in conflict_sets]


def random_select(conflict_sets, seed=42, **kwargs):
    rng = random.Random(seed)
    return [rng.choice(cs["members"]) for cs in conflict_sets]


METHODS = {
    "bran": bran_select,
    "majority_vote": majority_vote_select,
    "best_confidence": best_confidence_select,
    "last_writer_wins": last_writer_wins_select,
    "random": random_select,
}


# ── Fuzzy matching ──

def normalize(text):
    """Normalize text for matching: lowercase, strip markdown, collapse whitespace."""
    text = text.lower().strip()
    text = re.sub(r'\*+', '', text)  # strip markdown bold/italic
    text = re.sub(r'\s+', ' ', text)
    return text


def tokenize(text):
    """Extract meaningful tokens, dropping common stopwords."""
    stops = {"a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
             "has", "have", "had", "do", "does", "did", "in", "on", "at", "to",
             "for", "of", "with", "by", "from", "as", "it", "its", "that", "this",
             "and", "or", "but", "not", "no", "can", "will", "just", "about", "than",
             "also", "so", "very", "more", "most", "some", "any", "all", "both"}
    tokens = set(re.findall(r'[a-z0-9]+', text.lower()))
    return tokens - stops


def claim_matches_gt(claim, gt_triple):
    """Check if an extracted claim semantically matches a ground truth triple.

    Uses token overlap between the claim's full text and GT's key entities.
    """
    cs = normalize(claim.get("subject", ""))
    cp = normalize(claim.get("predicate", ""))
    co = normalize(claim.get("object", ""))
    claim_text = f"{cs} {cp} {co}"
    claim_tokens = tokenize(claim_text)

    gs, gp, go = [x.lower() for x in gt_triple]

    # Extract key tokens from GT
    gt_subj_tokens = tokenize(gs)
    gt_obj_tokens = tokenize(go)

    # Also split compound predicates on underscore
    gt_pred_parts = set()
    for part in gp.replace("_", " ").split():
        gt_pred_parts |= tokenize(part)

    # Subject: at least one key token must appear
    if gt_subj_tokens and not (gt_subj_tokens & claim_tokens):
        # Try substring match as fallback
        if gs not in claim_text and not any(t in claim_text for t in gt_subj_tokens if len(t) > 3):
            return False

    # Object: at least 40% of key tokens must appear
    if gt_obj_tokens:
        overlap = gt_obj_tokens & claim_tokens
        # Also check substring containment for multi-word objects
        substr_match = go in claim_text or claim_text in go
        if not substr_match and len(overlap) < max(1, len(gt_obj_tokens) * 0.4):
            return False

    # Meaningful predicate tokens should appear (skip pure linking verbs)
    linking = {"is", "are", "was", "has", "have", "had", "does", "do"}
    meaningful_pred = gt_pred_parts - linking
    if meaningful_pred:
        if not (meaningful_pred & claim_tokens):
            # Allow if subject+object match is very strong
            if gt_obj_tokens:
                obj_ratio = len(gt_obj_tokens & claim_tokens) / len(gt_obj_tokens)
            else:
                obj_ratio = 0
            if obj_ratio < 0.6:
                return False

    return True


# ── Evaluation ──

def evaluate_question(question_data, responses, method_name="bran"):
    """Evaluate one question with a given selection method.

    Returns per-question metrics:
    - recall: fraction of GT triples matched by any winner
    - precision: fraction of winners matching any GT triple
    - conflict_accuracy: for contradiction sets where one side matches GT,
      did the method pick the correct side?
    """
    ground_truth = question_data["ground_truth"]
    gt_triples = [(s, p, o) for s, p, o in ground_truth]

    # Parse contributions, filtering truncated claims and enriching evidence
    contributions = []
    for resp in responses:
        agent_claims = []
        for claim in resp.get("claims", []):
            # Skip truncated claims (object ends with dangling article/preposition)
            obj = claim.get("object", "")
            if re.search(r'\b(a|an|the|of|to|in|by|for|with|from)\s*$', obj.strip()):
                continue
            claim["agent"] = resp.get("agent", "unknown")
            claim["calibration"] = resp.get("calibration", 0.7)
            agent_claims.append(claim)

        # P2-style context-aware evidence association
        enrich_evidence_from_context(agent_claims, resp.get("raw_response", ""))
        contributions.extend(agent_claims)

    if not contributions:
        return {
            "recall": 0.0, "precision": 0.0,
            "conflict_correct": 0, "conflict_total": 0,
            "tp": 0, "fp": 0, "fn": len(gt_triples),
            "n_contributions": 0, "n_conflicts": 0,
        }

    conflict_sets = detect_conflicts(contributions)
    select_fn = METHODS[method_name]
    winners = select_fn(conflict_sets)

    # Metric 1: Precision — how many winners match some GT triple?
    tp = 0
    fp = 0
    matched_gt_for_prec = set()
    for w in winners:
        matched = False
        for i, gt in enumerate(gt_triples):
            if claim_matches_gt(w, gt):
                matched = True
                matched_gt_for_prec.add(i)
                break
        if matched:
            tp += 1
        else:
            fp += 1

    # Metric 2: Recall — how many GT triples matched by any winner?
    matched_gt = set()
    for i, gt in enumerate(gt_triples):
        for w in winners:
            if claim_matches_gt(w, gt):
                matched_gt.add(i)
                break
    fn = len(gt_triples) - len(matched_gt)
    recall = len(matched_gt) / len(gt_triples) if gt_triples else 0.0

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0

    # Metric 3: Conflict Resolution Accuracy
    # For contradiction sets: check if any member matches GT, and if so,
    # did the winner also match GT?
    conflict_correct = 0
    conflict_total = 0
    for cs, w in zip(conflict_sets, winners):
        if cs["type"] != "contradiction":
            continue

        # Check if any member of this conflict set matches any GT triple
        has_gt_member = False
        winner_matches_gt = False
        for gt in gt_triples:
            for m in cs["members"]:
                if claim_matches_gt(m, gt):
                    has_gt_member = True
                    break
            if claim_matches_gt(w, gt):
                winner_matches_gt = True

        if has_gt_member:
            conflict_total += 1
            if winner_matches_gt:
                conflict_correct += 1

    return {
        "recall": recall,
        "precision": precision,
        "conflict_correct": conflict_correct,
        "conflict_total": conflict_total,
        "tp": tp, "fp": fp, "fn": fn,
        "n_contributions": len(contributions),
        "n_conflicts": len(conflict_sets),
        "n_contradictions": sum(1 for cs in conflict_sets if cs["type"] == "contradiction"),
    }


# ── Bootstrap ──

def bootstrap_ci(values, n_bootstrap=1000, ci=0.95, seed=42):
    if not values:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(n_bootstrap):
        sample = [rng.choice(values) for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    alpha = (1 - ci) / 2
    lo = means[max(0, int(alpha * n_bootstrap))]
    hi = means[min(n_bootstrap - 1, int((1 - alpha) * n_bootstrap))]
    return sum(values) / n, lo, hi


# ── Main ──

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--bootstrap", type=int, default=1000)
    args = parser.parse_args()

    results_dir = Path(__file__).parent / "results"
    questions_file = Path(__file__).parent / "questions.json"

    with open(questions_file) as f:
        questions = json.load(f)

    # Per-method accumulators
    method_precisions = {m: [] for m in METHODS}
    method_recalls = {m: [] for m in METHODS}
    method_conflict_correct = {m: 0 for m in METHODS}
    method_conflict_total = {m: 0 for m in METHODS}
    method_tp = {m: 0 for m in METHODS}
    method_fp = {m: 0 for m in METHODS}
    method_fn = {m: 0 for m in METHODS}
    questions_evaluated = 0

    for q in questions:
        qid = q["id"]
        resp_file = results_dir / f"{qid}.json"
        if not resp_file.exists():
            continue

        with open(resp_file) as f:
            responses = json.load(f)
        if not responses:
            continue

        questions_evaluated += 1

        for method_name in METHODS:
            r = evaluate_question(q, responses, method_name)
            method_precisions[method_name].append(r["precision"])
            method_recalls[method_name].append(r["recall"])
            method_conflict_correct[method_name] += r["conflict_correct"]
            method_conflict_total[method_name] += r["conflict_total"]
            method_tp[method_name] += r["tp"]
            method_fp[method_name] += r["fp"]
            method_fn[method_name] += r["fn"]

            if args.verbose and method_name == "bran":
                ca = f"{r['conflict_correct']}/{r['conflict_total']}" if r['conflict_total'] > 0 else "n/a"
                print(f"  {qid}: {r['n_contributions']} claims, "
                      f"{r['n_contradictions']} contradictions, "
                      f"P={r['precision']:.0%} R={r['recall']:.0%} CA={ca}")

    if questions_evaluated == 0:
        print("No results found. Run collect.py first.")
        sys.exit(1)

    # ── Summary ──
    print(f"\n{'='*85}")
    print(f"BRAN REAL-AGENT EVALUATION — {questions_evaluated} questions × 5 LLM agents")
    print(f"Models: llama3.2:3b, mistral, gemma2:2b, phi3:mini, qwen2.5:3b")
    print(f"{'='*85}")

    print(f"\n{'Method':<20} {'Precision':>10} {'95% CI':>18} {'Recall':>8} {'95% CI':>18} {'CR Acc':>8}")
    print("-" * 85)

    for method_name in ["bran", "majority_vote", "best_confidence", "last_writer_wins", "random"]:
        precs = method_precisions[method_name]
        recs = method_recalls[method_name]
        p_point, p_lo, p_hi = bootstrap_ci(precs, args.bootstrap)
        r_point, r_lo, r_hi = bootstrap_ci(recs, args.bootstrap)

        cc = method_conflict_correct[method_name]
        ct = method_conflict_total[method_name]
        cr_acc = f"{cc}/{ct}={cc/ct:.0%}" if ct > 0 else "n/a"

        label = f"→ {method_name}" if method_name == "bran" else f"  {method_name}"
        print(f"{label:<20} {p_point:>9.1%} [{p_lo:.1%},{p_hi:.1%}] "
              f"{r_point:>7.1%} [{r_lo:.1%},{r_hi:.1%}] "
              f"{cr_acc:>8}")

    # ── Aggregate counts ──
    print(f"\n{'Method':<20} {'TP':>6} {'FP':>6} {'FN':>6} {'Macro-P':>9} {'Macro-R':>9}")
    print("-" * 60)
    for method_name in ["bran", "majority_vote", "best_confidence", "last_writer_wins", "random"]:
        tp = method_tp[method_name]
        fp = method_fp[method_name]
        fn = method_fn[method_name]
        mp = sum(method_precisions[method_name]) / len(method_precisions[method_name])
        mr = sum(method_recalls[method_name]) / len(method_recalls[method_name])
        label = f"→ {method_name}" if method_name == "bran" else f"  {method_name}"
        print(f"{label:<20} {tp:>6} {fp:>6} {fn:>6} {mp:>8.1%} {mr:>8.1%}")

    # ── Per-category breakdown ──
    print(f"\n{'Category':<28} {'Bran P':>8} {'MajV P':>8} {'Bran R':>8} {'MajV R':>8}")
    print("-" * 65)

    cat_results = defaultdict(lambda: {m: {"prec": [], "rec": []} for m in METHODS})
    eval_idx = 0
    for q in questions:
        resp_file = results_dir / f"{q['id']}.json"
        if not resp_file.exists():
            continue
        cat = q.get("category", "unknown")
        for m in METHODS:
            cat_results[cat][m]["prec"].append(method_precisions[m][eval_idx])
            cat_results[cat][m]["rec"].append(method_recalls[m][eval_idx])
        eval_idx += 1

    for cat in sorted(cat_results.keys()):
        n = len(cat_results[cat]["bran"]["prec"])
        bp = sum(cat_results[cat]["bran"]["prec"]) / n
        mp = sum(cat_results[cat]["majority_vote"]["prec"]) / n
        br = sum(cat_results[cat]["bran"]["rec"]) / n
        mr = sum(cat_results[cat]["majority_vote"]["rec"]) / n
        print(f"  {cat} (n={n}){' '*(20-len(cat)-len(str(n)))} {bp:>7.1%} {mp:>7.1%} {br:>7.1%} {mr:>7.1%}")

    # ── Save ──
    output = {
        "questions_evaluated": questions_evaluated,
        "models": ["llama3.2:3b", "mistral", "gemma2:2b", "phi3:mini", "qwen2.5:3b"],
        "methods": {},
    }
    for m in METHODS:
        p_point, p_lo, p_hi = bootstrap_ci(method_precisions[m], args.bootstrap)
        r_point, r_lo, r_hi = bootstrap_ci(method_recalls[m], args.bootstrap)
        cc = method_conflict_correct[m]
        ct = method_conflict_total[m]
        output["methods"][m] = {
            "precision": round(p_point, 4), "precision_ci": [round(p_lo, 4), round(p_hi, 4)],
            "recall": round(r_point, 4), "recall_ci": [round(r_lo, 4), round(r_hi, 4)],
            "conflict_resolution_accuracy": round(cc / ct, 4) if ct > 0 else None,
            "conflict_correct": cc, "conflict_total": ct,
            "tp": method_tp[m], "fp": method_fp[m], "fn": method_fn[m],
        }

    out_file = results_dir / "evaluation.json"
    with open(out_file, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nFull results: {out_file}")


if __name__ == "__main__":
    main()
