#!/usr/bin/env python3
"""
Eval v3: run the ACTUAL Rust reducer (`bran --reduce`) on real-agent responses,
check Python<->Rust equivalence, and score with both graders of evaluate_v2.py.

Datasets
  v3      real-agent-eval/v3/results/q*.json  (re-collected; file order = recorded
          arrival order; seq = arrival_seq*1000 + sentence index)
  v1orig  real-agent-eval/results/q*.json     (original responses; seq = agent LIST
          order*1000 + sentence index -- no arrival times were recorded)

Claims are produced exactly as in evaluate_v2.py: ../collect.py extraction (stored
in the result files), then evaluate_v2.load_contributions (truncation filter +
context-aware evidence association). The same contribution dicts feed both the
Python reducer and the Rust lowering.

Lowering to the `--reduce` schema (bran/src/main.rs run_reduce):
  id            sha256(qid|agent|k|s|p|o)[:16]      (k = claim index within response)
  agent_id      response agent;  calibration map {agent: response calibration (0.7)}
  kind          ASSERTION
  canonical_form {subject, predicate, object, polarity: AFFIRM}  (identity: the shared
                 regex extraction produces no NEGATE forms and no critiques)
  confidence, lowering_confidence  as extracted
  evidence      each item -> {type, source: item.text, weight, reachable: true,
                 verification: UNVERIFIED}
  raw_text      raw_sentence;  criteria = []  (constraint alignment = 1.0, as Python)

Rust policies (all passed in the input JSON, binary unchanged)
  native     default BranCompiler policy (arity-aware slot keys)
  forced     default policy, but values.incompatible_values groups EVERY object of
             each predicate into one group -> every (s,p) is an exclusive slot, the
             Python harness's conflict structure
  *_rec0     weights with recency = 0
  *_evonly   weights [1,0,0,0,0], deadband 0 -> final = ev * lowering_factor

Usage:  python3 evaluate_v3.py --bin <path/to/bran> [--bootstrap 10000 --seed 42]
"""

import argparse
import copy
import csv
import hashlib
import json
import math
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import evaluate_v1 as v1  # noqa: E402
import evaluate_v2 as ev2  # noqa: E402

OUT = HERE / "results"
LIST_ORDER = ["llama3.2_3b", "mistral", "gemma2_2b", "phi3_mini", "qwen2.5_3b"]

DEFAULT_POLICY = {
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
UNIQUE_PREDICATES = {"has_capital", "is_classified_as", "are_caused_by", "became_capital_in",
                     "was_reclassified_in", "is_located_in", "was_temporary_capital_until",
                     "contributes", "is", "has", "raises", "recommends", "is_causal_for"}


def norm_obj(o):
    """ir.rs normalize_object: collapse whitespace, lowercase."""
    return " ".join(o.split()).lower()


# ── Loading & lowering ──────────────────────────────────────────

DATASET_DIRS = {"v3": [("", OUT)], "v1orig": [("", HERE.parent / "results")],
                "v3rep2": [("", HERE / "results_rep2")],
                "v3pool": [("", OUT), ("~rep2", HERE / "results_rep2")]}


def load_dataset(name):
    """List of (question, responses, run_tag). v3* files are sorted by arrival_seq."""
    qs = json.load(open(HERE.parent / "questions.json"))
    out = []
    for tag, d in DATASET_DIRS[name]:
        for q in qs:
            f = d / f"{q['id']}.json"
            if not f.exists():
                continue
            resps = json.load(open(f))
            if name != "v1orig":
                resps = sorted(resps, key=lambda r: r["arrival_seq"])
            if resps:
                out.append((q, resps, tag))
    return out


def build_contribs(q, resps):
    """evaluate_v2.load_contributions + per-contribution seq and id."""
    contribs = ev2.load_contributions(resps, associate=True)
    arrival = {}
    for i, r in enumerate(resps):
        arrival[r["agent"]] = r.get("arrival_seq", i)   # v1orig: list position
    k = Counter()
    for c in contribs:
        a = c["agent"]
        assert k[a] < 1000
        c["_seq"] = arrival[a] * 1000 + k[a]
        c["_id"] = hashlib.sha256(
            f"{q['id']}|{a}|{k[a]}|{c['subject']}|{c['predicate']}|{c['object']}".encode()
        ).hexdigest()[:16]
        k[a] += 1
    # contribution order must equal seq order (Python recency uses list position)
    assert [c["_seq"] for c in contribs] == sorted(c["_seq"] for c in contribs)
    return contribs


def lower(c):
    return {
        "id": c["_id"], "agent_id": c["agent"], "agent_name": c["agent"],
        "kind": "ASSERTION",
        "canonical_form": {"subject": c["subject"], "predicate": c["predicate"],
                           "object": c["object"], "polarity": "AFFIRM"},
        "confidence": c["confidence"],
        "lowering_confidence": c["lowering_confidence"],
        "evidence": [{"type": e["type"], "source": e.get("text", ""), "weight": e["weight"],
                      "reachable": True, "verification": "UNVERIFIED"}
                     for e in c.get("evidence", [])],
        "raw_text": c.get("raw_sentence", ""),
        "seq": c["_seq"],
    }


def policy_for(contribs, variant):
    p = copy.deepcopy(DEFAULT_POLICY)
    base, _, mod = variant.partition("_")
    if base == "forced":
        groups = defaultdict(set)
        for c in contribs:
            groups[c["predicate"].lower()].add(norm_obj(c["object"]))
        p["values"]["incompatible_values"] = {
            pr: {"__all_objects__": sorted(objs)} for pr, objs in sorted(groups.items())}
    if mod in ("rec0", "rec0nodb"):
        p["weights"] = [0.35, 0.2, 0.25, 0.0, 0.15]
    if mod in ("nodb", "rec0nodb"):
        p["deadband_threshold"] = 0
    elif mod == "evonly":
        p["weights"] = [1.0, 0.0, 0.0, 0.0, 0.0]
        p["deadband_threshold"] = 0
    return p


def run_rust(binary, q, contribs, variant, dsname, tag=""):
    cal = {c["agent"]: c["calibration"] for c in contribs}
    inp = {"intent": q["question"], "criteria": [], "calibration": cal,
           "policy": policy_for(contribs, variant), "contributions": [lower(c) for c in contribs]}
    d = OUT / "rust" / dsname / (q["id"] + tag)
    d.mkdir(parents=True, exist_ok=True)
    fin = d / f"{variant}.in.json"
    json.dump(inp, open(fin, "w"), indent=1, sort_keys=True)
    r = subprocess.run([binary, "--reduce", str(fin), "--no-color"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"bran --reduce failed on {fin}: {r.stderr}")
    out = json.loads(r.stdout)
    json.dump(out, open(d / f"{variant}.out.json", "w"), indent=1, sort_keys=True)
    return out


# ── Python mirror of compiler.rs P4/P5 (assertion-only inputs) ──

SR = {"CITATION": 0.75, "TOOL_RESULT": 0.75, "EMPIRICAL": 0.75, "AUTHORITY": 0.5, "REASONING": 0.3}
TW = {"TOOL_RESULT": 1.0, "EMPIRICAL": 0.9, "CITATION": 0.8, "AUTHORITY": 0.5, "REASONING": 0.3}
SQ = {"TOOL_RESULT": 1.0, "REASONING": 1.0}   # else UNVERIFIED quality 0.40
LF = {"HIGH": 1.0, "MEDIUM": 0.85, "LOW": 0.5}


def q_round(x):
    """Rust f64::round (half away from zero) of x*10000."""
    y = x * 10000.0
    return int(math.floor(y + 0.5)) if y >= 0 else -int(math.floor(-y + 0.5))


def rust_ev(c, citers):
    if not c.get("evidence"):
        return 0.0
    t = 0.0
    for e in c["evidence"]:
        typ = e["type"]
        base = e["weight"] * TW[typ] * SQ.get(typ, 0.40) * SR[typ]
        n = len(citers.get(e.get("text", "").lower(), ()))
        n = n if n else 1
        t += base * (1.2 if n >= 3 else 1.1 if n >= 2 else 0.9)
    return min(max(t, 0.0), 1.0)


def schulze(members, dims, eps=100):
    n = len(members)
    if n < 2:
        return members[0] if members else None
    d = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                d[i][j] = sum(1 for k in range(5) if dims[members[i]][k] > dims[members[j]][k] + eps)
    p = [[d[i][j] if i != j else 0 for j in range(n)] for i in range(n)]
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


def mirror(contribs, *, arity, low_excluded, evidence, quantized, deadband, weights=None):
    """Return (slots, admitted). slots: list of dict(key, type, members(ids), winner,
    scores_q, in_deadband). arity: 'python' | 'forced' | 'native'."""
    w = weights or DEFAULT_POLICY["weights"]
    by_id = {c["_id"]: c for c in contribs}
    order = sorted(contribs, key=lambda c: (c["_seq"], c["_id"]))
    citers = defaultdict(set)
    for c in order:
        for e in c.get("evidence", []):
            citers[e.get("text", "").lower()].add(c["agent"])
    groups = defaultdict(list)
    for c in order:
        if low_excluded and c["lowering_confidence"] == "LOW":
            continue
        if arity == "python":
            key = (c["subject"].lower().strip(), c["predicate"].lower().strip())
        else:
            s, p = c["subject"].lower(), c["predicate"].lower()
            if arity == "forced" or p in UNIQUE_PREDICATES:
                key = (s, p)
            else:
                o = norm_obj(c["object"])
                grp = next((g for g, objs in DEFAULT_POLICY["values"]["incompatible_values"]
                            .get(p, {}).items() if o in objs), None)
                key = (s, p, "<" + grp + ">") if grp else (s, p, o)
        groups[key].append(c["_id"])
    objkey = (lambda c: c["object"].lower().strip()) if arity == "python" else \
        (lambda c: norm_obj(c["object"]))
    slots, in_slot = [], set()
    cand_sets = []
    for key in sorted(groups):
        mem = groups[key]
        distinct = {objkey(by_id[i]) for i in mem}
        if len(distinct) > 1:
            cand_sets.append(("CONTRADICTION", key, mem))
            in_slot.update(mem)
    if arity != "python":
        # compiler.rs P4 redundancy sets: identical (s, p, o, polarity) value keys
        # from >1 members, none of which is already in a contradiction.
        vgroups = defaultdict(list)
        for c in order:
            if low_excluded and c["lowering_confidence"] == "LOW":
                continue
            vgroups[(c["subject"].lower(), c["predicate"].lower(), c["object"].lower())].append(c["_id"])
        for vk in sorted(vgroups):
            mem = vgroups[vk]
            if len(mem) > 1 and not (set(mem) & in_slot):
                cand_sets.append(("REDUNDANCY", vk, mem))
    for typ, key, mem in cand_sets:
        n = len(mem)
        denom = max(n - 1, 1)
        scores, dims = {}, {}
        for rank, i in enumerate(mem):
            c = by_id[i]
            ev = rust_ev(c, citers) if evidence == "rust" else v1.score_evidence(c.get("evidence", []))
            conf = min(c["confidence"] * c["calibration"], 1.0)
            rec = rank / denom
            raw = w[0] * ev + w[1] * conf + w[2] * 1.0 + w[3] * rec + w[4] * 1.0
            fs = raw * LF[c["lowering_confidence"]]
            scores[i] = fs
            dims[i] = [q_round(ev), q_round(conf), q_round(1.0), q_round(rec), q_round(1.0)]
        if quantized:
            sq = {i: q_round(scores[i]) for i in mem}
            best, bq = None, None
            for i in mem:
                if bq is None or sq[i] > bq:
                    best, bq = i, sq[i]
        else:
            sq = {i: scores[i] for i in mem}
            best = sorted(mem, key=lambda i: -scores[i])[0]
        inb = False
        if deadband and quantized:
            top2 = sorted(sq.values(), reverse=True)
            if top2[0] - top2[1] < 500:
                inb = True
                cand = [i for i in mem if top2[0] - sq[i] < 500]
                best = schulze(cand, dims)
        slots.append({"key": key, "type": typ, "members": list(mem), "winner": best,
                      "scores_q": sq, "in_deadband": inb})
        in_slot.update(mem)
    admitted = {s["winner"] for s in slots}
    for c in order:
        if c["_id"] in in_slot:
            continue
        if low_excluded and c["lowering_confidence"] == "LOW":
            continue
        admitted.add(c["_id"])      # redundancy duplicates collapse to the same object
    return slots, admitted


LADDER = [
    ("L0_python", dict(arity="python", low_excluded=False, evidence="python", quantized=False, deadband=False)),
    ("L1_low_excluded", dict(arity="python", low_excluded=True, evidence="python", quantized=False, deadband=False)),
    ("L2_arity", dict(arity="native", low_excluded=True, evidence="python", quantized=False, deadband=False)),
    ("L3_evidence_math", dict(arity="native", low_excluded=True, evidence="rust", quantized=False, deadband=False)),
    ("L4_quantized_tiebreak", dict(arity="native", low_excluded=True, evidence="rust", quantized=True, deadband=False)),
    ("L5_deadband_schulze", dict(arity="native", low_excluded=True, evidence="rust", quantized=True, deadband=True)),
]
FORCED_MIRROR = dict(arity="forced", low_excluded=True, evidence="rust", quantized=True, deadband=True)


def project(pyset_ids, slots, admitted, by_id):
    """Outcome of a reducer for a Python conflict set: the set of normalized
    objects among the members it admits."""
    adm = [i for i in pyset_ids if i in admitted]
    return frozenset(norm_obj(by_id[i]["object"]) for i in adm), adm


# ── Grading helpers ─────────────────────────────────────────────

def correct(c, gt, grader):
    return ev2.correct_any(c, gt, grader)


def outcome_correct(adm_ids, by_id, gt, grader):
    """Correct iff the reducer outputs at least one member for the slot and every
    member it outputs matches gold."""
    return int(bool(adm_ids) and all(correct(by_id[i], gt, grader) for i in adm_ids))


def rust_index(out):
    sel = [s for s in out["selections"] if s["type"] == "CONTRADICTION"]
    return sel, set(out["admitted"])


def rust_outcome(pyset_ids, out):
    """('select', winner) if a Rust contradiction slot holds members of this set,
    else ('dissolved', admitted members)."""
    sels, adm = rust_index(out)
    ids = set(pyset_ids)
    hit = [s for s in sels if set(s["members"]) & ids]
    if len(hit) == 1 and set(hit[0]["members"]) <= ids:
        return "select", [hit[0]["winner"]], hit[0]
    if hit:
        return "split", [i for i in pyset_ids if i in adm], hit
    return "dissolved", [i for i in pyset_ids if i in adm], None


METHODS_A = ["rust", "rust_rec0", "rust_nodb", "rust_rec0nodb", "rust_evonly", "python_bran", "python_bran_listorder",
             "python_no_recency", "evidence_only_py", "majority", "first_member", "last_member"]
METHODS_B = ["rust", "rust_rec0", "rust_nodb", "rust_rec0nodb", "rust_evonly", "python_bran_on_slot", "majority",
             "first_member", "last_member"]


def latest_candidate(sel, by_id):
    """1 if the Rust winner is the latest-arriving member among the deadband
    candidates (members within 500 quantized points of the top score)."""
    if not sel or not sel["in_deadband"]:
        return 0
    top = max(sel["scores_q"].values())
    cand = [i for i in sel["members"] if top - sel["scores_q"][i] < 500]
    return int(sel["winner"] == max(cand, key=lambda i: by_id[i]["_seq"]))


def evonly_pick(sel, by_id):
    """argmax Rust ev (= score_q / lowering factor), ties -> earliest canonical member."""
    best, bv = None, None
    for i in sel["members"]:
        v = sel["scores_q"][i] / LF[by_id[i]["lowering_confidence"]]
        if bv is None or v > bv + 1e-9:
            best, bv = i, v
    return best


def listorder_bran(members):
    """Python reducer with recency ranked by agent LIST order (paper's harness)."""
    order = sorted(range(len(members)), key=lambda i: (LIST_ORDER.index(members[i]["agent"]), i))
    reordered = [members[i] for i in order]
    return order[ev2.bran_idx(reordered)]


def analyse(dsname, data, binary, args):
    runs = []
    for q, resps, tag in data:
        contribs = build_contribs(q, resps)
        outs = {v: run_rust(binary, q, contribs, v, dsname, tag)
                for v in [f"{b}{m}" for b in ("native", "forced")
                          for m in ("", "_rec0", "_evonly", "_nodb", "_rec0nodb")]}
        runs.append({"tag": tag, "q": q, "gt": [tuple(x) for x in q["ground_truth"]],
                     "contribs": contribs, "by_id": {c["_id"]: c for c in contribs},
                     "outs": outs, "cs": v1.detect_conflicts(contribs)})

    summary = {"dataset": dsname, "questions": len(runs),
               "contributions": sum(len(r["contribs"]) for r in runs)}

    # ── Mirror validation against the binary ─────────────────
    mv = {"native": [0, 0], "forced": [0, 0]}
    for r in runs:
        for variant, opts in [("native", LADDER[-1][1]), ("forced", FORCED_MIRROR)]:
            slots, adm = mirror(r["contribs"], **opts)
            rs, radm = r["outs"][variant]["selections"], set(r["outs"][variant]["admitted"])
            mine = {frozenset(s["members"]): (s["type"], s["winner"], s["scores_q"], s["in_deadband"]) for s in slots}
            theirs = {frozenset(s["members"]): (s["type"], s["winner"], s["scores_q"], s["in_deadband"]) for s in rs}
            mv[variant][0] += 1
            if mine != theirs or adm != radm:
                mv[variant][1] += 1
    summary["mirror_validation"] = {k: {"questions": a, "questions_mismatched": b} for k, (a, b) in mv.items()}

    # ── L0 must equal evaluate_v2.bran_idx ───────────────────
    l0_bad = 0
    for r in runs:
        slots, _ = mirror(r["contribs"], **LADDER[0][1])
        win = {frozenset(s["members"]): s["winner"] for s in slots}
        for cs in r["cs"]:
            if cs["type"] != "contradiction":
                continue
            ids = [m["_id"] for m in cs["members"]]
            if win.get(frozenset(ids)) != ids[ev2.bran_idx(cs["members"])]:
                l0_bad += 1
    summary["mirror_L0_vs_evaluate_v2_mismatches"] = l0_bad

    # ── Equivalence: Python v2 reducer vs Rust native, every Python set ──
    eq_rows = []
    cause_counter = Counter()
    for r in runs:
        by_id = r["by_id"]
        lad = [(name, mirror(r["contribs"], **opts)) for name, opts in LADDER]
        for cs in r["cs"]:
            ids = [m["_id"] for m in cs["members"]]
            py_w = ids[ev2.bran_idx(cs["members"])]
            py_sig = frozenset([norm_obj(by_id[py_w]["object"])])
            kind, rust_adm, _ = rust_outcome(ids, r["outs"]["native"])
            rust_sig = frozenset(norm_obj(by_id[i]["object"]) for i in rust_adm)
            sigs = [project(ids, s, a, by_id)[0] for _, (s, a) in lad]
            sigs[0] = py_sig
            changed = [LADDER[i][0] for i in range(1, len(sigs)) if sigs[i] != sigs[i - 1]]
            agree = py_sig == rust_sig
            if agree:
                cause = ""
            else:
                cause = changed[0] if changed else "UNEXPLAINED"
                if cause == "L1_low_excluded" and cs["type"] != "contradiction":
                    cause = "L1_singleton_low_rejected"
            cause_counter[(cs["type"], cause or "agree")] += 1
            eq_rows.append({"question": r["q"]["id"], "type": cs["type"], "subject": cs["key"][0],
                            "predicate": cs["key"][1], "n_members": len(ids),
                            "n_low": sum(by_id[i]["lowering_confidence"] == "LOW" for i in ids),
                            "python_winner_object": norm_obj(by_id[py_w]["object"]),
                            "rust_outcome": kind,
                            "rust_output_objects": " || ".join(sorted(rust_sig)),
                            "agree": int(agree), "primary_cause": cause,
                            "all_changing_steps": ";".join(changed),
                            "ladder_final_equals_rust": int(sigs[-1] == rust_sig)})
    ev2.write_csv(OUT / f"equivalence_{dsname}.csv", eq_rows, list(eq_rows[0].keys()))
    summary["equivalence"] = {
        "python_sets": len(eq_rows),
        "agree": sum(r["agree"] for r in eq_rows),
        "ladder_final_equals_rust": sum(r["ladder_final_equals_rust"] for r in eq_rows),
        "by_type_and_cause": {f"{t}|{c}": n for (t, c), n in sorted(cause_counter.items())},
    }
    for t in ["contradiction", "redundancy"]:
        sub = [x for x in eq_rows if x["type"] == t]
        summary["equivalence"][f"{t}_sets"] = len(sub)
        summary["equivalence"][f"{t}_agree"] = sum(x["agree"] for x in sub)

    # ── Table A: Python-structured slots (forced policy) ──────
    summary["tables"] = {}
    for gname, grader in ev2.GRADERS.items():
        rowsA = []
        for r in runs:
            gt, by_id = r["gt"], r["by_id"]
            for cs in r["cs"]:
                if cs["type"] != "contradiction":
                    continue
                mem = cs["members"]
                flags = [correct(m, gt, grader) for m in mem]
                if not any(flags):
                    continue
                ids = [m["_id"] for m in mem]
                fl = dict(zip(ids, flags))
                row = {"question": r["q"]["id"], "run": r["tag"], "_by_id": by_id,
                       "category": r["q"]["category"],
                       "subject": cs["key"][0], "predicate": cs["key"][1],
                       "n_members": len(mem), "n_agents": len({m["agent"] for m in mem}),
                       "n_low": sum(m["lowering_confidence"] == "LOW" for m in mem),
                       "n_correct_members": sum(flags), "decisive": int(not all(flags))}
                for meth, var in [("rust", "forced"), ("rust_rec0", "forced_rec0"),
                                  ("rust_nodb", "forced_nodb"), ("rust_rec0nodb", "forced_rec0nodb")]:
                    kind, adm, sel = rust_outcome(ids, r["outs"][var])
                    row[meth] = outcome_correct(adm, by_id, gt, grader)
                    if meth == "rust":
                        row["rust_outcome"] = kind
                        row["rust_in_deadband"] = int(bool(sel and kind == "select" and sel["in_deadband"]))
                        row["_sel"] = sel if kind == "select" else None
                kind, adm, sel = rust_outcome(ids, r["outs"]["forced_evonly"])
                row["rust_evonly"] = (int(fl[evonly_pick(sel, by_id)]) if kind == "select"
                                      else outcome_correct(adm, by_id, gt, grader))
                row["python_bran"] = int(flags[ev2.bran_idx(mem)])
                row["python_bran_listorder"] = int(flags[listorder_bran(mem)])
                row["python_no_recency"] = int(flags[ev2.bran_idx(mem, {"recency": 0.0})])
                row["evidence_only_py"] = int(flags[ev2.evidence_only_idx(mem)])
                row["majority"] = int(flags[ev2.majority_idx(mem)])
                row["first_member"] = int(flags[0])
                row["last_member"] = int(flags[-1])
                row["_fl"] = fl
                row["_ev_sel"] = sel if kind == "select" else None
                row["_latest"] = latest_candidate(row["_sel"], by_id)
                rowsA.append(row)
        # ── Table B: Rust-native slots ──
        rowsB = []
        for r in runs:
            gt, by_id = r["gt"], r["by_id"]
            sels, _ = rust_index(r["outs"]["native"])
            rec0 = {frozenset(s["members"]): s for s in rust_index(r["outs"]["native_rec0"])[0]}
            nodb = {frozenset(s["members"]): s for s in rust_index(r["outs"]["native_nodb"])[0]}
            r0nd = {frozenset(s["members"]): s for s in rust_index(r["outs"]["native_rec0nodb"])[0]}
            evo = {frozenset(s["members"]): s for s in rust_index(r["outs"]["native_evonly"])[0]}
            for s in sels:
                mem = [by_id[i] for i in s["members"]]          # canonical (seq) order
                flags = [correct(m, gt, grader) for m in mem]
                if not any(flags):
                    continue
                fl = dict(zip(s["members"], flags))
                fk = frozenset(s["members"])
                row = {"question": r["q"]["id"], "run": r["tag"], "_by_id": by_id,
                       "category": r["q"]["category"], "slot": s["slot"],
                       "n_members": len(mem), "n_agents": len({m["agent"] for m in mem}),
                       "n_correct_members": sum(flags), "decisive": int(not all(flags)),
                       "rust": int(fl[s["winner"]]), "rust_in_deadband": int(s["in_deadband"]),
                       "rust_rec0": int(fl[rec0[fk]["winner"]]),
                       "rust_nodb": int(fl[nodb[fk]["winner"]]),
                       "rust_rec0nodb": int(fl[r0nd[fk]["winner"]]),
                       "rust_evonly": int(fl[evonly_pick(evo[fk], by_id)]),
                       "python_bran_on_slot": int(flags[ev2.bran_idx(mem)]),
                       "majority": int(flags[ev2.majority_idx(mem)]),
                       "first_member": int(flags[0]), "last_member": int(flags[-1]),
                       "_fl": fl, "_sel": s, "_ev_sel": evo[fk],
                       "_latest": latest_candidate(s, by_id)}
                rowsB.append(row)
        for tname, rows, methods in [("A_python_slots", rowsA, METHODS_A), ("B_rust_native_slots", rowsB, METHODS_B)]:
            summary["tables"][f"{tname}|{gname}"] = table_stats(rows, methods, args, r_by_q={x["q"]["id"]: x for x in runs})
            base = ["question", "run", "category"] + (["subject", "predicate", "n_low", "rust_outcome"] if tname.startswith("A") else ["slot"])
            ev2.write_csv(OUT / f"paired_decisions_{dsname}_{tname}_{gname}.csv", rows,
                          base + ["n_members", "n_agents", "n_correct_members", "decisive", "rust_in_deadband"] + methods)
            mrows = [margin_row(x, {q["q"]["id"]: q for q in runs}) for x in rows if x["decisive"]]
            ev2.write_csv(OUT / f"separation_margins_{dsname}_{tname}_{gname}.csv", mrows,
                          ["question", "run", "slot", "n_scored", "n_correct", "n_incorrect", "rust_correct",
                           "ev_gap", "ev_separated", "score_gap", "score_separated",
                           "top2_score_gap", "in_deadband", "status"])
            summary["tables"][f"{tname}|{gname}"]["margins"] = margin_stats(mrows)
            if tname.startswith("B") and gname == "v2":
                summary["precision_sheet_rows"] = write_adjudication(dsname, runs)
    return summary


def table_stats(rows, methods, args, r_by_q):
    dec = [r for r in rows if r["decisive"]]
    st = {"eligible": len(rows), "decisive": len(dec),
          "eligible_questions": len({r["question"] for r in rows}),
          "decisive_questions": len({r["question"] for r in dec}),
          "decisive_per_question": dict(Counter(r["question"] for r in dec)),
          "accuracy": {}}
    if "rust_outcome" in (rows[0] if rows else {}):
        st["rust_outcome_counts"] = dict(Counter(r["rust_outcome"] for r in rows))
        st["rust_outcome_counts_decisive"] = dict(Counter(r["rust_outcome"] for r in dec))
    st["rust_in_deadband"] = {"eligible": sum(r["rust_in_deadband"] for r in rows),
                              "decisive": sum(r["rust_in_deadband"] for r in dec)}
    agc = defaultdict(lambda: [0, 0])
    firsts = Counter()
    for r in dec:
        ids = sorted(r["_fl"], key=lambda i: r["_by_id"][i]["_seq"])
        firsts[r["_by_id"][ids[0]]["agent"]] += 1
        for i in ids:
            agc[r["_by_id"][i]["agent"]][0] += int(r["_fl"][i])
            agc[r["_by_id"][i]["agent"]][1] += 1
    st["decisive_member_correct_by_agent"] = {a: v for a, v in sorted(agc.items())}
    st["decisive_first_member_agent"] = dict(firsts)
    st["majority_same_correctness_as_first_member"] = {
        "eligible": sum(r["majority"] == r["first_member"] for r in rows),
        "decisive": sum(r["majority"] == r["first_member"] for r in dec)}
    db = [r for r in rows if r["rust_in_deadband"]]
    st["deadband_winner_is_latest_candidate"] = {
        "eligible_in_deadband": len(db), "latest": sum(r["_latest"] for r in db),
        "decisive_in_deadband": sum(1 for r in db if r["decisive"]),
        "decisive_latest": sum(r["_latest"] for r in db if r["decisive"])}
    for m in methods:
        st["accuracy"][m] = {"eligible_correct": sum(r[m] for r in rows),
                             "decisive_correct": sum(r[m] for r in dec)}
    st["vs_majority"] = {}
    for m in methods:
        if m == "majority" or not rows:
            continue
        b = sum(1 for r in rows if r[m] and not r["majority"])
        c = sum(1 for r in rows if r["majority"] and not r[m])
        st["vs_majority"][m] = {"b": b, "c": c, "p_exact": ev2.mcnemar_exact(b, c)}
    if rows:
        pt, lo, hi, nq = ev2.cluster_bootstrap(rows, "rust", "majority", args.bootstrap, args.seed)
        st["bootstrap_rust_minus_majority"] = {"diff": pt, "ci95": [lo, hi], "n_questions": nq,
                                               "resamples": args.bootstrap, "seed": args.seed}
        if dec:
            pt, lo, hi, nq = ev2.cluster_bootstrap(dec, "rust", "majority", args.bootstrap, args.seed)
            st["bootstrap_rust_minus_majority_decisive"] = {"diff": pt, "ci95": [lo, hi], "n_questions": nq}
    return st


def margin_row(row, runs):
    by_id = row["_by_id"]
    sel, evs = row.get("_sel"), row.get("_ev_sel")
    out = {"question": row["question"], "run": row["run"], "slot": row.get("slot") or f"({row['subject']}, {row['predicate']})",
           "rust_correct": row["rust"]}
    if sel is None or evs is None:
        out.update(status="no_rust_slot", n_scored=0, n_correct="", n_incorrect="", ev_gap="",
                   score_gap="", ev_separated="n/a", score_separated="n/a", top2_score_gap="", in_deadband="")
        return out
    fl = row["_fl"]
    mem = sel["members"]
    corr = [i for i in mem if fl[i]]
    inc = [i for i in mem if not fl[i]]
    out["n_scored"], out["n_correct"], out["n_incorrect"] = len(mem), len(corr), len(inc)
    if not corr or not inc:
        out.update(status="not_decisive_after_rust_membership", ev_gap="", score_gap="",
                   ev_separated="n/a", score_separated="n/a", top2_score_gap="", in_deadband="")
        return out
    evq = {i: evs["scores_q"][i] / LF[by_id[i]["lowering_confidence"]] for i in mem}
    sq = sel["scores_q"]
    evg = min(evq[i] for i in corr) - max(evq[i] for i in inc)
    sg = min(sq[i] for i in corr) - max(sq[i] for i in inc)
    t2 = sorted(sq.values(), reverse=True)
    out.update(status="ok", ev_gap=round(evg / 10000, 6), score_gap=round(sg / 10000, 6),
               ev_separated=int(evg > 500), score_separated=int(sg > 500),
               top2_score_gap=round((t2[0] - t2[1]) / 10000, 6), in_deadband=int(sel["in_deadband"]))
    return out


def margin_stats(mrows):
    ok = [m for m in mrows if m["status"] == "ok"]
    st = {"decisive_rows": len(mrows), "with_rust_scores": len(ok),
          "status_counts": dict(Counter(m["status"] for m in mrows))}
    for k in ["ev_separated", "score_separated"]:
        tab = Counter((m[k], m["rust_correct"]) for m in ok)
        st[k] = {"separated": sum(m[k] for m in ok), "sep_correct": tab[(1, 1)], "sep_wrong": tab[(1, 0)],
                 "nosep_correct": tab[(0, 1)], "nosep_wrong": tab[(0, 0)]}
    st["ev_gap_positive"] = sum(1 for m in ok if m["ev_gap"] > 0)
    st["in_deadband"] = sum(m["in_deadband"] for m in ok)
    return st


def write_adjudication(dsname, runs):
    """Rust-native admitted contributions that fail the stricter (v2) grader."""
    rows = []
    for r in runs:
        gt, by_id = r["gt"], r["by_id"]
        out = r["outs"]["native"]
        for i in out["admitted"]:
            w = by_id[i]
            if correct(w, gt, ev2.match_v2):
                continue
            ng, j = ev2.nearest_gold(w, gt)
            rows.append({"dataset": dsname, "question": r["q"]["id"], "run": r["tag"], "contribution_id": i,
                         "agent": w["agent"], "seq": w["_seq"],
                         "claim_text": w.get("raw_sentence", ""),
                         "triple": f"({w['subject']} | {w['predicate']} | {w['object']})",
                         "nearest_gold_triple": f"({ng[0]} | {ng[1]} | {ng[2]})",
                         "nearest_jaccard": round(j, 4),
                         "v1_grader_match": int(correct(w, gt, v1.claim_matches_gt)),
                         "auto_category_heuristic": ev2.adjudication_category(w, gt),
                         "human_label": ""})
    ev2.write_csv(OUT / f"precision_adjudication_{dsname}.csv", rows, list(rows[0].keys()) if rows else ["human_label"])
    admitted_total = sum(len(r["outs"]["native"]["admitted"]) for r in runs)
    return {"admitted_total": admitted_total, "rows_failing_v2": len(rows),
            "heuristic_distribution": dict(Counter(x["auto_category_heuristic"] for x in rows))}


# ── Arrival-order analysis (v3 raw records) ─────────────────────

def kendall_tau(a, b):
    pos = {x: i for i, x in enumerate(b)}
    n, s = len(a), 0
    for i in range(n):
        for j in range(i + 1, n):
            s += 1 if pos[a[i]] < pos[a[j]] else -1
    return s / (n * (n - 1) / 2)


def arrival_analysis(rdir=OUT):
    rows, taus = [], []
    mean_rank = defaultdict(list)
    same, overlap_q, maxconc = 0, 0, []
    max_loaded = 0
    for f in sorted((rdir / "raw").glob("q*.json")):
        raw = json.load(open(f))
        arr = [m.replace(":", "_") for m in raw["arrival_order"]]
        lst = [m.replace(":", "_") for m in raw["list_order"]]
        disp = [m.replace(":", "_") for m in raw["dispatch_order"]]
        tau = kendall_tau(arr, lst)
        taus.append(tau)
        same += int(arr == lst)
        for rk, a in enumerate(arr):
            mean_rank[a].append(rk)
        rs = raw["responses"]
        ev = sorted([(r["start_mono"], 1) for r in rs] + [(r["end_mono"], -1) for r in rs])
        cur = mx = 0
        for _, d in ev:
            cur += d
            mx = max(mx, cur)
        maxconc.append(mx)
        for _, names in raw.get("ollama_ps_samples", []):
            max_loaded = max(max_loaded, len([n for n in names if not str(n).startswith("error")]))
        waits = {r["agent"]: round(r["elapsed_s"] - (r["ollama_meta"] or {}).get("total_duration", 0) / 1e9, 2)
                 for r in rs}
        rows.append({"question": raw["id"], "list_order": " ".join(lst), "dispatch_order": " ".join(disp),
                     "arrival_order": " ".join(arr), "kendall_tau_vs_list": round(tau, 4),
                     "arrival_equals_list": int(arr == lst),
                     "last_arrival": arr[-1], "list_last": lst[-1],
                     "errors": sum(1 for r in rs if r["error"]),
                     "client_minus_server_s": json.dumps(waits)})
    if not rows:
        return {}
    ev2.write_csv(OUT / ("arrival_order.csv" if rdir == OUT else f"arrival_order_{rdir.name}.csv"),
                  rows, list(rows[0].keys()))
    return {"questions": len(rows), "arrival_equals_list_order": same,
            "mean_kendall_tau_vs_list": round(sum(taus) / len(taus), 4),
            "last_arrival_is_qwen(list-last)": sum(1 for r in rows if r["last_arrival"] == "qwen2.5_3b"),
            "last_arrival_counts": dict(Counter(r["last_arrival"] for r in rows)),
            "mean_arrival_rank_by_agent": {a: round(sum(v) / len(v), 3) for a, v in sorted(mean_rank.items())},
            "max_in_flight_requests_per_question": dict(Counter(maxconc)),
            "max_models_resident_seen_in_api_ps": max_loaded,
            "errors": sum(r["errors"] for r in rows)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", required=True)
    ap.add_argument("--bootstrap", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--datasets", nargs="*", default=["v3", "v1orig"])
    args = ap.parse_args()
    binhash = hashlib.sha256(open(args.bin, "rb").read()).hexdigest()
    # results_rep2/ is an INCOMPLETE replicate (stopped at 18/55 questions by request);
    # it is not analysed. The v3rep2/v3pool dataset names remain for a future full run.
    res = {"binary": args.bin, "binary_sha256": binhash, "arrival": arrival_analysis(), "datasets": {}}
    for ds in args.datasets:
        data = load_dataset(ds)
        res["datasets"][ds] = analyse(ds, data, args.bin, args)
        pol = json.load(open(next((OUT / "rust" / ds).glob("*/native.out.json"))))["policy_hash"]
        res["datasets"][ds]["native_policy_hash"] = pol
    json.dump(res, open(OUT / "evaluation_v3.json", "w"), indent=2)
    print(json.dumps(res, indent=1)[:20000])


if __name__ == "__main__":
    main()
