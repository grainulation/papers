#!/usr/bin/env python3
"""Assemble the eval-v5 item sets (Swarm 3, lane L4). Spec: v3/SWARM3_DESIGN.md §4, §6.2, §8.

No model calls, no network. Downloaded files are read as DATA only (paths passed as arguments).
Run with an isolated interpreter from the repo root:

  python3 -I real-agent-eval/v5/benchmark/build_benchmark_v5.py \
      --v4-benchmark real-agent-eval/v4/benchmark \
      --validation tools/evidence/support/validation \
      --v4-conf-run-manifest real-agent-eval/v4/results/conf/run_manifest.json \
      --out real-agent-eval/v5/benchmark

What it does
  1. Verifies every source download against the sha256 recorded in the v4 benchmark manifest.
  2. Rebuilds the v4 *eligible* pools with the frozen v4 builder (loaded read-only by path) and
     asserts that they reproduce the v4 eligibility counts and v4 item files byte-for-byte.
  3. Dev split = the 160 v4 dev items, re-rendered for open retrieval (SciFact abstract removed).
  4. Fresh pool per source = eligible
       - v4 dev (160)                       -> they are v5 dev
       - v4 confirmatory primary (600)      -> v4 Stage B; v4 unblinding must not inform v5 items
       - every SciFact claim used by the support checker (slice / pilot / injection bases)
       - any item whose normalised question/claim text equals an excluded item's text
       - items sharing a normalised text with an item of a different gold label (all dropped)
       - within-pool duplicate texts (lowest id kept)
     The 400 v4 *extension* items (never collected; v4 Stage B ran --n-items 600) stay eligible,
     as the design's pool counts require.
  5. Confirmatory draw, seed 20261201, never conditioned on model output:
       primary   TruthfulQA 300, SciFact 250, PopQA 250, FEVER 200       (orders    0 ..  999)
       extension TruthfulQA 160, PopQA 133, FEVER 107 (SciFact exhausted) (orders 1000 .. 1399)
     Stratified by gold label within SciFact (proportional to the fresh pool) and by popularity
     stratum within PopQA (round-robin, as v4). Sources are interleaved by a smooth weighted
     round-robin so every prefix of the frozen order is balanced (the stopping rule takes a prefix).
  6. Writes items_dev.jsonl, items_confirmatory.jsonl, reserve_order.json (the frozen order of the
     unused fresh items, for any pre-declared quota move), exclusion_proofs.json, manifest.json.

Prompts are NOT rendered here: the v5 prompts are owned by lane L3 (real-agent-eval/v5/prompts/).
Items carry the structured fields the harness, checker (L5) and grader (G-AK) need.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import random
import re
import sys
from collections import Counter, OrderedDict

SEED = 20261201
BUILD_VERSION = "v5-benchmark-1.0.0"
PRIMARY = OrderedDict([("truthfulqa", 300), ("scifact", 250), ("popqa", 250), ("fever", 200)])
EXTENSION = OrderedDict([("truthfulqa", 160), ("popqa", 133), ("fever", 107)])   # 400, ∝ primary quotas
SOURCES = ("truthfulqa", "popqa", "fever", "scifact")
CORPUS_BY_SOURCE = {"truthfulqa": "fever17", "popqa": "fever17", "fever": "fever17", "scifact": "scifact"}
BINARY = ["SUPPORTED", "REFUTED"]
ENTITY_MAX_CHARS = 60

# v5-benchmark-1.1.0: pre-declared TruthfulQA quota switch (real-agent-eval/v5/PREREGISTRATION.md §6.1-§6.3)
BUILD_VERSION_SWITCH = "v5-benchmark-1.1.0"
SWITCH_K = OrderedDict([("popqa", 150), ("fever", 150)])            # reserve[k][0:150], in reserve order
TQA_STRATUM_N = 100                                                  # first 100 TQA primary items, frozen order
SWITCH_QUOTAS = OrderedDict([("scifact", 250), ("popqa", 400), ("fever", 350), ("truthfulqa", 100)])
PREREG_HASH = {   # prereg §6.1/§6.2; list hashes = sha256("\n".join(ids) + "\n"), set hashes = the same over the sorted ids
    "popqa_reserve_0_150": "875f7a97e4aae4d43a1488cebc7e3e62366cb655daf11265172e99ff2f4f73c0",
    "fever_reserve_0_150": "a076d66464c5e7406483743936312360b350904b4c4bb7288b585526d7de28dc",
    "tqa_stratum_100": "60811e82f13d0041a024c7bae47144a8b241dce79a5f1cb443206d354ce17cc7",
    "sorted_1100": "d649d362afe2848921318319adf7a438e0f8cde7cdf983017323e2f24bed19a5",
    "sorted_not_collected_600": "ed08e1b0f4fa4341ac13424cf08755c3f4cfd91d6726df2a18326d8954522a05",
}
# every checker-validation slice (0.1.0 SciFact slice/pilot/injection, 0.2.0 fresh slices, both FEVER slices);
# the local checker validates on fresh2 + slice.jsonl, so it is covered. Asserted disjoint, not subtracted.
# Value = (id field, text_required_zero). Text-level disjointness is required for the sets the 1.0.0 draw had to
# exclude; the slices L5 drew later (excluding v5 items by id) are required disjoint by id, and any same-text
# collisions (FEVER paper_dev repeats claims under different ids) are listed in exclusion_proofs.json.
VALIDATION_ALL = OrderedDict([
    ("slice.jsonl", ("id", True)), ("pilot.jsonl", ("id", True)), ("injection.jsonl", ("base_id", True)),
    ("scifact_slice_fresh2.jsonl", ("id", False)), ("fever_slice.jsonl", ("id", False)),
    ("fever_slice_fresh2.jsonl", ("id", False))])


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_ids(ids):
    return hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()


def norm_text(s):
    s = re.sub(r"\s+", " ", s.strip().lower())
    return re.sub(r"[\s.?!]+$", "", s)


def jsonl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_v4_builder(path):
    spec = importlib.util.spec_from_file_location("v4_build_benchmark", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sid_of(v4_id):
    assert v4_id.startswith("v4-"), v4_id
    return v4_id[3:]


# ------------------------------------------------------------------ v4 -> v5 record

def fever_evidence(dl):
    """FEVER paper_dev evidence sentences per claim id, as sorted unique [page, sentence_id]."""
    out = {}
    for line in open(os.path.join(dl, "fever", "paper_dev.jsonl"), encoding="utf-8"):
        d = json.loads(line)
        ev = {(e[2], e[3]) for group in d["evidence"] for e in group if e[2] is not None}
        out[d["id"]] = [[p, s] for p, s in sorted(ev)]
    return out


def scifact_evidence(dl):
    base = os.path.join(dl, "scifact", "extracted", "data")
    out = {}
    for split in ("train", "dev"):
        for d in jsonl(os.path.join(base, f"claims_{split}.jsonl")):
            out[f"claims_{split}:{d['id']}"] = sorted(int(k) for k in (d.get("evidence") or {}))
    return out


def to_v5(v4, fev, sci):
    """Re-render one v4 pool record as a v5 item (no prompt; open retrieval)."""
    key = v4["source"]["key"]
    sid = sid_of(v4["id"])
    vid = f"v5-{sid}"
    src = dict(v4["source"])
    gold = dict(v4["gold"])
    triples = []
    rec = OrderedDict()
    rec["id"] = vid
    if key == "truthfulqa":
        rec["item_type"] = "multiple_choice"
        letters = [o["letter"] for o in v4["options"]]
        schema = {"enum": letters}
        stratum = "all"
        triples.append({"subject": vid, "predicate": "answer", "object": gold["answer"],
                        "derivation": "G-TQA-1: letter of the unique mc1_targets entry with value 1, after the "
                                      "v4 seeded option shuffle Random('20261021:truthfulqa:<sid>') (reused unchanged)"})
    elif key == "popqa":
        rec["item_type"] = "entity"
        schema = {"type": "string", "maxLength": ENTITY_MAX_CHARS}
        # the subject label lives in the v4 readability triple G-POP-2; lift it into source for L5's template
        src["subj"] = v4["gold_triples"][1]["subject"]
        stratum = src["stratum"]
        triples.append({"subject": vid, "predicate": "answer", "object": gold["answer"],
                        "derivation": "G-POP-1: PopQA obj (Wikidata object label); accepted aliases = possible_answers, verbatim"})
    elif key == "fever":
        rec["item_type"] = "binary_claim"
        schema = {"enum": BINARY}
        stratum = gold["answer"]
        gold["evidence_sentences"] = fev[int(src["source_id"])]
        triples.append({"subject": vid, "predicate": "answer", "object": gold["answer"],
                        "derivation": "G-FEV-1: FEVER label SUPPORTS->SUPPORTED, REFUTES->REFUTED"})
    else:  # scifact, open retrieval: the abstract is NOT part of the item
        rec["item_type"] = "binary_claim"
        schema = {"enum": BINARY}
        stratum = gold["answer"]
        gold["evidence_doc_ids"] = sci[src["source_id"]]
        triples.append({"subject": vid, "predicate": "answer", "object": gold["answer"],
                        "derivation": "G-SCI-1o: SciFact rationale label; every evidence abstract of the claim carries "
                                      "the same label (mixed-label claims excluded), so the label is defined against "
                                      "the corpus, not one abstract; SUPPORT->SUPPORTED, CONTRADICT->REFUTED"})
    rec["source"] = src
    rec["corpus"] = CORPUS_BY_SOURCE[key]
    rec["question"] = v4["question"]
    if "options" in v4:
        rec["options"] = v4["options"]
    rec["answer_format"] = v4["answer_format"]
    rec["answer_schema"] = schema
    rec["gold"] = gold
    rec["gold_triples"] = triples
    rec["predicate_type"] = "functional"
    rec["stratum"] = stratum
    rec["contested_rationale"] = v4["contested_rationale"] if key != "scifact" else (
        "Expert-written biomedical claim answered by open retrieval over the SciFact corpus; CONTRADICT claims are "
        "negations/alterations of cited findings and v4 majorities affirmed them (design §4).")
    rec["review_note"] = v4["review_note"]
    rec["v4_id"] = v4["id"]
    rec["build_version"] = BUILD_VERSION
    return rec


# ------------------------------------------------------------------ ordering helpers

def round_robin(groups):
    """Interleave lists in sorted-key order; exhausted groups drop out (v4 PopQA rule)."""
    groups = OrderedDict((k, list(groups[k])) for k in sorted(groups))
    out = []
    while any(groups.values()):
        for k in groups:
            if groups[k]:
                out.append(groups[k].pop(0))
    return out


def smooth_wrr(streams, quotas):
    """Smooth weighted round-robin: at each step emit from the stream furthest behind its quota share
    (ties -> fixed source order). Every prefix is within one item of the quota proportions."""
    total = sum(quotas.values())
    taken = {k: 0 for k in quotas}
    out = []
    for n in range(1, total + 1):
        k = max(quotas, key=lambda s: (n * quotas[s] / total - taken[s], -list(quotas).index(s)))
        out.append(streams[k][taken[k]])
        taken[k] += 1
    return out


def proportional(n, counts):
    """Largest-remainder allocation of n across strata in proportion to counts (ties by key)."""
    tot = sum(counts.values())
    raw = {k: n * c / tot for k, c in counts.items()}
    alloc = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: (-(raw[k] - alloc[k]), k))[: n - sum(alloc.values())]:
        alloc[k] += 1
    return alloc


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v4-benchmark", required=True)
    ap.add_argument("--validation", required=True)
    ap.add_argument("--v4-conf-run-manifest", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--archive", default=None, help="archived 1.0.0 outputs (default <out>/1.0.0)")
    a = ap.parse_args()

    v4b = a.v4_benchmark
    dl = os.path.join(v4b, "downloads")
    v4_manifest_p = os.path.join(v4b, "manifest.json")
    v4_manifest = json.load(open(v4_manifest_p, encoding="utf-8"))
    v4_builder_p = os.path.join(v4b, "scripts", "build_benchmark.py")
    checks = OrderedDict()

    # 1. source files must equal the v4-recorded hashes
    file_paths = {
        "truthfulqa": {"TruthfulQA.csv": "truthfulqa/TruthfulQA.csv", "data/mc_task.json": "truthfulqa/mc_task.json"},
        "popqa": {"popQA.tsv": "popqa/popQA.tsv"},
        "fever": {"paper_dev.jsonl": "fever/paper_dev.jsonl"},
        "scifact": {"claims_train.jsonl": "scifact/extracted/data/claims_train.jsonl",
                    "claims_dev.jsonl": "scifact/extracted/data/claims_dev.jsonl",
                    "corpus.jsonl": "scifact/extracted/data/corpus.jsonl",
                    "data.tar.gz": "scifact/data.tar.gz"},
    }
    for key, files in file_paths.items():
        for name, rel in files.items():
            got = sha256_file(os.path.join(dl, rel))
            want = v4_manifest["sources"][key]["files"][name]
            if got != want:
                raise SystemExit(f"download hash mismatch {key}/{name}: {got} != {want}")
    checks["downloads_match_v4_manifest"] = True

    # 2. v4 eligible pools via the frozen v4 builder; must reproduce v4 counts and item files
    v4mod = load_v4_builder(v4_builder_p)
    srcmeta = OrderedDict()
    pools = OrderedDict()
    for key, fn in (("truthfulqa", v4mod.build_truthfulqa), ("popqa", v4mod.build_popqa),
                    ("fever", v4mod.build_fever), ("scifact", v4mod.build_scifact)):
        items, _exc = fn(dl, srcmeta)
        if len(items) != v4_manifest["eligibility"][key]["eligible"]:
            raise SystemExit(f"{key}: eligible {len(items)} != v4 manifest")
        pools[key] = {it["id"]: it for it in items}
    for name in ("items_dev.jsonl", "items_confirmatory.jsonl"):
        if sha256_file(os.path.join(v4b, name)) != v4_manifest["outputs"][name]:
            raise SystemExit(f"v4 {name} differs from its manifest hash")
    v4_dev = jsonl(os.path.join(v4b, "items_dev.jsonl"))
    v4_conf = jsonl(os.path.join(v4b, "items_confirmatory.jsonl"))
    strip = ("split", "tier", "order", "system_prompt", "build_version")
    for it in v4_dev + v4_conf:
        pool_rec = pools[it["source"]["key"]][it["id"]]
        if {k: v for k, v in it.items() if k not in strip} != pool_rec:
            raise SystemExit(f"v4 item {it['id']} does not match the rebuilt pool record")
    checks["v4_items_reproduced_from_pools"] = True

    v4_dev_ids = [it["id"] for it in v4_dev]
    v4_primary_ids = [it["id"] for it in v4_conf if it["tier"] == "primary"]
    v4_extension_ids = [it["id"] for it in v4_conf if it["tier"] == "extension"]

    # v4 Stage B: what was requested must be exactly the primary tier (so the extension is uncollected)
    rm = json.load(open(a.v4_conf_run_manifest, encoding="utf-8"))
    requested = set()
    for s in rm["sessions"]:
        requested |= set(s["items_requested"])
    stage_b = {"run_manifest": a.v4_conf_run_manifest, "run_manifest_sha256": sha256_file(a.v4_conf_run_manifest),
               "argv": [s.get("argv") for s in rm["sessions"]], "items_requested": len(requested),
               "requested_equals_v4_primary": requested == set(v4_primary_ids),
               "requested_in_v4_extension": len(requested & set(v4_extension_ids))}
    if requested - set(v4_primary_ids):
        raise SystemExit("v4 Stage B requested items outside the primary tier; recompute the fresh pools")

    # checker-validation claims (SciFact slice, pilot, injection bases)
    val_files = OrderedDict([("slice.jsonl", "id"), ("pilot.jsonl", "id"), ("injection.jsonl", "base_id")])
    val_ids, val_texts, val_meta = set(), set(), OrderedDict()
    for name, k in val_files.items():
        p = os.path.join(a.validation, name)
        rows = jsonl(p)
        ids = {r[k] for r in rows}
        val_ids |= ids
        val_texts |= {norm_text(r["claim"]) for r in rows}
        val_meta[name] = {"sha256": sha256_file(p), "rows": len(rows), "claim_ids": len(ids)}
    sci_eligible = set(pools["scifact"])
    val_in_eligible = val_ids & sci_eligible

    # 3. dev split = v4 dev, re-rendered
    fev, sci = fever_evidence(dl), scifact_evidence(dl)
    dev = []
    for k, it in enumerate(v4_dev):
        r = to_v5(pools[it["source"]["key"]][it["id"]], fev, sci)
        r["split"], r["tier"], r["order"] = "dev", "dev", k
        dev.append(r)

    # 4. fresh pools
    excluded_ids = set(v4_dev_ids) | set(v4_primary_ids) | val_ids
    excluded_texts = val_texts | {norm_text(pools[src][i]["question"])
                                  for src in SOURCES for i in pools[src] if i in excluded_ids}
    accounting = OrderedDict()
    fresh = OrderedDict()
    for key in SOURCES:
        ids = sorted(pools[key])
        acc = OrderedDict(eligible=len(ids))
        acc["minus_v4_dev"] = sum(i in set(v4_dev_ids) for i in ids)
        acc["minus_v4_primary_stage_b"] = sum(i in set(v4_primary_ids) for i in ids)
        rest = [i for i in ids if i not in set(v4_dev_ids) and i not in set(v4_primary_ids)]
        acc["minus_checker_validation"] = sum(i in val_ids for i in rest)
        rest = [i for i in rest if i not in val_ids]
        txt_hit = [i for i in rest if norm_text(pools[key][i]["question"]) in excluded_texts]
        acc["minus_text_match_to_excluded"] = len(txt_hit)
        acc["text_match_ids"] = txt_hit
        rest = [i for i in rest if i not in set(txt_hit)]
        golds = {}
        for i in rest:
            golds.setdefault(norm_text(pools[key][i]["question"]), set()).add(pools[key][i]["gold"]["answer"])
        conflict = [i for i in rest if len(golds[norm_text(pools[key][i]["question"])]) > 1]
        acc["minus_same_text_conflicting_gold"] = len(conflict)
        acc["conflicting_gold_ids"] = conflict
        rest = [i for i in rest if i not in set(conflict)]
        seen, dedup, dup = set(), [], []
        for i in rest:                                   # ids sorted -> lowest id kept
            t = norm_text(pools[key][i]["question"])
            (dup if t in seen else dedup).append(i)
            seen.add(t)
        acc["minus_within_pool_duplicate_text"] = len(dup)
        acc["duplicate_text_ids"] = dup
        acc["fresh"] = len(dedup)
        acc["fresh_of_which_v4_extension"] = sum(i in set(v4_extension_ids) for i in dedup)
        accounting[key] = acc
        fresh[key] = dedup

    # 5. seeded draw
    def shuffled(key, ids, tag="order"):
        ids = sorted(ids)
        random.Random(f"{SEED}:{key}:{tag}").shuffle(ids)
        return ids

    streams = OrderedDict()
    strat_notes = OrderedDict()
    # TruthfulQA, FEVER: plain seeded shuffle
    for key in ("truthfulqa", "fever"):
        streams[key] = shuffled(key, fresh[key])
    # PopQA: per-stratum shuffle, then round-robin over strata (balanced within every tier)
    by_s = OrderedDict()
    for i in fresh["popqa"]:
        by_s.setdefault(pools["popqa"][i]["source"]["stratum"], []).append(i)
    by_s = OrderedDict((s, shuffled("popqa", v, "stratum:" + s)) for s, v in sorted(by_s.items()))
    strat_notes["popqa_fresh_by_stratum"] = {s: len(v) for s, v in by_s.items()}
    streams["popqa"] = round_robin(by_s)
    # SciFact: proportional allocation by gold label for the 250 primary, label lists interleaved smoothly
    by_l = OrderedDict()
    for i in fresh["scifact"]:
        by_l.setdefault(pools["scifact"][i]["gold"]["answer"], []).append(i)
    by_l = OrderedDict((l, shuffled("scifact", v, "label:" + l)) for l, v in sorted(by_l.items()))
    need_sci = PRIMARY["scifact"]
    if len(fresh["scifact"]) < need_sci:
        raise SystemExit(f"scifact: fresh pool {len(fresh['scifact'])} < {need_sci}")
    alloc = proportional(need_sci, {l: len(v) for l, v in by_l.items()})
    strat_notes["scifact_fresh_by_label"] = {l: len(v) for l, v in by_l.items()}
    strat_notes["scifact_primary_allocation"] = alloc
    sci_drawn = smooth_wrr({l: by_l[l][:alloc[l]] for l in alloc}, alloc)
    sci_left = [i for l in by_l for i in by_l[l][alloc[l]:]]
    streams["scifact"] = sci_drawn + sci_left

    for key in PRIMARY:
        need = PRIMARY[key] + EXTENSION.get(key, 0)
        if len(streams[key]) < need:
            raise SystemExit(f"{key}: fresh pool {len(streams[key])} < {need}")

    prim_streams = {k: streams[k][:PRIMARY[k]] for k in PRIMARY}
    ext_streams = {k: streams[k][PRIMARY[k]:PRIMARY[k] + EXTENSION[k]] for k in EXTENSION}
    order_ids = [(i, "primary") for i in smooth_wrr(prim_streams, PRIMARY)] + \
                [(i, "extension") for i in smooth_wrr(ext_streams, EXTENSION)]
    key_of = {i: k for k in SOURCES for i in pools[k]}
    conf = []
    for n, (i, tier) in enumerate(order_ids):
        r = to_v5(pools[key_of[i]][i], fev, sci)
        r["split"], r["tier"], r["order"] = "confirmatory", tier, n
        r["v4_tier"] = "extension_uncollected" if i in set(v4_extension_ids) else None
        conf.append(r)
    for r in dev:
        r["v4_tier"] = "dev"

    used = {i for i, _ in order_ids}
    reserve = OrderedDict((k, ["v5-" + sid_of(i) for i in streams[k] if i not in used]) for k in SOURCES)

    # 6. exclusion proofs
    conf_v4ids = {r["v4_id"] for r in conf}
    dev_v4ids = {r["v4_id"] for r in dev}
    conf_texts = {norm_text(r["question"]) for r in conf}
    dev_texts = {norm_text(r["question"]) for r in dev}
    primary_texts = {norm_text(pools[key_of[i]][i]["question"]) for i in v4_primary_ids}
    proofs = OrderedDict()
    proofs["method"] = ("Intersections are computed on the v4-namespace id (v4-<sid>) and on normalised question/claim "
                        "text (lowercase, whitespace collapsed, trailing .?! stripped). Each exclusion set is listed "
                        "with the sha256 of its newline-joined sorted ids.")
    proofs["sets"] = OrderedDict([
        ("v4_dev", {"n": len(v4_dev_ids), "ids_sha256": sha256_ids(v4_dev_ids)}),
        ("v4_confirmatory_primary_stage_b", {"n": len(v4_primary_ids), "ids_sha256": sha256_ids(v4_primary_ids)}),
        ("v4_confirmatory_extension_uncollected", {"n": len(v4_extension_ids), "ids_sha256": sha256_ids(v4_extension_ids),
                                                   "status": "eligible for v5 (design §4 pool counts include them)"}),
        ("checker_validation_scifact", {"files": val_meta, "n_claim_ids": len(val_ids), "ids_sha256": sha256_ids(val_ids),
                                        "n_in_v4_eligible_pool": len(val_in_eligible),
                                        "n_in_v4_eligible_pool_by_label": dict(sorted(Counter(
                                            pools["scifact"][i]["gold"]["answer"] for i in val_in_eligible).items())),
                                        "n_not_eligible_NEI": len(val_ids - sci_eligible),
                                        "n_distinct_claim_texts": len(val_texts)}),
    ])
    proofs["v4_stage_b"] = stage_b
    inter = OrderedDict()
    inter["confirmatory_x_v4_dev_ids"] = len(conf_v4ids & set(v4_dev_ids))
    inter["confirmatory_x_v4_primary_ids"] = len(conf_v4ids & set(v4_primary_ids))
    inter["confirmatory_x_v4_stage_b_requested_ids"] = len(conf_v4ids & requested)
    inter["confirmatory_x_validation_ids"] = len(conf_v4ids & val_ids)
    inter["confirmatory_x_validation_texts"] = len(conf_texts & val_texts)
    inter["confirmatory_x_v4_dev_texts"] = len(conf_texts & dev_texts)
    inter["confirmatory_x_v4_primary_texts"] = len(conf_texts & primary_texts)
    inter["confirmatory_x_dev_ids"] = len(conf_v4ids & dev_v4ids)
    inter["confirmatory_duplicate_ids"] = len(conf) - len(conf_v4ids)
    inter["confirmatory_duplicate_texts_within_source"] = sum(
        v - 1 for v in Counter((r["source"]["key"], norm_text(r["question"])) for r in conf).values() if v > 1)
    inter["reserve_x_confirmatory"] = len({x for v in reserve.values() for x in v} & {r["id"] for r in conf})
    proofs["required_zero"] = inter
    disclosed = OrderedDict()
    disclosed["dev_x_validation_ids"] = len(dev_v4ids & val_ids)
    disclosed["dev_x_validation_texts"] = len(dev_texts & val_texts)
    disclosed["dev_x_v4_primary_texts"] = len(dev_texts & primary_texts)
    disclosed["confirmatory_from_v4_extension"] = sum(r["v4_tier"] == "extension_uncollected" for r in conf)
    disclosed["confirmatory_from_v4_extension_by_source"] = dict(Counter(
        r["source"]["key"] for r in conf if r["v4_tier"] == "extension_uncollected"))
    proofs["disclosed_not_required_zero"] = disclosed
    bad = {k: v for k, v in inter.items() if v}
    proofs["all_required_zero"] = not bad
    checks["exclusions_hold"] = not bad
    if bad:
        raise SystemExit(f"exclusion proof failed: {bad}")

    # ---------------------------------------------------------------- 1.0.0 must equal the archived build
    def ser_jsonl(rows):
        return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows).encode("utf-8")

    def ser_json(obj):
        return (json.dumps(obj, indent=1, ensure_ascii=False) + "\n").encode("utf-8")

    reserve_doc = {
        "note": "Fresh, unused items per source in frozen seeded order (seed %d). Any pre-declared quota move "
                "(design §2.2 TruthfulQA switch) takes the next items of the receiving source from this list, in "
                "order, appended after order 1399; nothing here was selected on model output." % SEED,
        "reserve": reserve, "counts": {k: len(v) for k, v in reserve.items()}}
    b_dev, b_conf100, b_res = ser_jsonl(dev), ser_jsonl(conf), ser_json(reserve_doc)
    archive = a.archive or os.path.join(a.out, "1.0.0")
    arch_manifest = json.load(open(os.path.join(archive, "manifest.json"), encoding="utf-8"))
    for name, b in (("items_dev.jsonl", b_dev), ("items_confirmatory.jsonl", b_conf100), ("reserve_order.json", b_res)):
        want = arch_manifest["outputs"][name]
        if hashlib.sha256(b).hexdigest() != want or sha256_file(os.path.join(archive, name)) != want:
            raise SystemExit(f"1.0.0 rebuild of {name} differs from the archived 1.0.0 output")
    checks["v1_0_0_rebuilt_byte_identical"] = ["items_dev.jsonl", "items_confirmatory.jsonl", "reserve_order.json"]
    checks["v1_0_0_exclusions_hold"] = proofs["all_required_zero"]

    # ---------------------------------------------------------------- 1.1.0: TruthfulQA quota switch
    by_src = lambda key, tier: [r for r in conf if r["source"]["key"] == key and r["tier"] == tier]  # noqa: E731
    add_ids = OrderedDict((k, reserve[k][:SWITCH_K[k]]) for k in SWITCH_K)
    t_stratum = by_src("truthfulqa", "primary")[:TQA_STRATUM_N]

    def lhash(ids):                     # prereg §6.1: ids joined by \n with a trailing \n
        return hashlib.sha256(("\n".join(ids) + "\n").encode("utf-8")).hexdigest()

    got_hash = OrderedDict([
        ("popqa_reserve_0_150", lhash(add_ids["popqa"])), ("fever_reserve_0_150", lhash(add_ids["fever"])),
        ("tqa_stratum_100", lhash([r["id"] for r in t_stratum]))])
    for k, v in got_hash.items():
        if v != PREREG_HASH[k]:
            raise SystemExit(f"switch list {k} sha256 {v} != prereg {PREREG_HASH[k]}")

    def retained(r, tier):
        r = json.loads(json.dumps(r))
        r["tier"] = tier
        return r

    def added(vid):
        v4id = "v4-" + vid[3:]
        r = to_v5(pools[key_of[v4id]][v4id], fev, sci)
        r["build_version"] = BUILD_VERSION_SWITCH
        r["split"], r["tier"] = "confirmatory", "primary"
        r["v4_tier"] = "extension_uncollected" if v4id in set(v4_extension_ids) else None
        r["switch_added"] = True
        return r

    streams11 = OrderedDict([
        ("scifact", [retained(r, "primary") for r in by_src("scifact", "primary")]),
        ("popqa", [retained(r, "primary") for r in by_src("popqa", "primary")] + [added(i) for i in add_ids["popqa"]]),
        ("fever", [retained(r, "primary") for r in by_src("fever", "primary")] + [added(i) for i in add_ids["fever"]]),
        ("truthfulqa", [retained(r, "tqa_stratum") for r in t_stratum]),
    ])
    for k, q in SWITCH_QUOTAS.items():
        assert len(streams11[k]) == q, (k, len(streams11[k]), q)
    conf11 = smooth_wrr(streams11, SWITCH_QUOTAS)
    for n, r in enumerate(conf11):
        r["order"] = n

    ids11 = [r["id"] for r in conf11]
    old_by_id = {r["id"]: r for r in conf}
    not_collected = [r["id"] for r in conf if r["id"] not in set(ids11)]
    got_hash["sorted_1100"] = lhash(sorted(ids11))
    got_hash["sorted_not_collected_600"] = lhash(sorted(not_collected))
    for k in ("sorted_1100", "sorted_not_collected_600"):
        if got_hash[k] != PREREG_HASH[k]:
            raise SystemExit(f"{k} sha256 {got_hash[k]} != prereg {PREREG_HASH[k]}")

    # retained records equal 1.0.0 on every field but order and tier
    n_ret, n_diff = 0, 0
    for r in conf11:
        if r.get("switch_added"):
            continue
        n_ret += 1
        o = old_by_id[r["id"]]
        if {k: v for k, v in r.items() if k not in ("order", "tier")} != {k: v for k, v in o.items() if k not in ("order", "tier")}:
            n_diff += 1
    if n_ret != 800 or n_diff:
        raise SystemExit(f"retained records: {n_ret} kept, {n_diff} differ")
    checks["retained_800_equal_except_order_tier"] = True

    # G-AK gold-consistency (each item's own gold answer must grade correct; no model output involved)
    spec = importlib.util.spec_from_file_location("v4_answer_key", os.path.join(v4b, "scripts", "answer_key.py"))
    ak = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ak)
    gak_fail = [r["id"] for r in dev + conf11
                if not ak.grade(r, ak.parse_answer(r, "ANSWER: " + r["gold"]["answer"]), "ANSWER: " + r["gold"]["answer"])]
    schema_fail = [r["id"] for r in dev + conf11
                   if ("enum" in r["answer_schema"] and r["gold"]["answer"] not in r["answer_schema"]["enum"])
                   or len(r["gold"]["answer"]) > r["answer_schema"].get("maxLength", 10 ** 9)]
    if gak_fail or schema_fail:
        raise SystemExit(f"gold-consistency failed: G-AK {gak_fail[:5]} schema {schema_fail[:5]}")
    checks["gold_consistency_G_AK"] = {"items": len(dev) + len(conf11), "failures": 0,
                                       "answer_key_sha256": sha256_file(os.path.join(v4b, "scripts", "answer_key.py"))}

    # ---------------------------------------------------------------- exclusion proofs, 1.1.0
    def vkey(i):
        return i if i.startswith("v4-") else "v4-" + i

    all_val = OrderedDict()
    collisions = []
    by_text = {}
    for r in dev + conf:
        by_text.setdefault(norm_text(r["question"]), []).append(r)
    for name, (k, _treq) in VALIDATION_ALL.items():
        p = os.path.join(a.validation, name)
        rows = jsonl(p)
        for vr in rows:
            for it in by_text.get(norm_text(vr["claim"]), []):
                collisions.append(OrderedDict([
                    ("slice", name), ("slice_id", vr[k]), ("slice_gold", vr["gold"]), ("item_id", it["id"]),
                    ("item_gold", it["gold"]["answer"]), ("text", vr["claim"]),
                    ("in_1_0_0", f"{it['split']}/{it['tier']}/order {it['order']}"),
                    ("in_1_1_0_collect", it["id"] in set(ids11)), ("in_v5_dev", it["split"] == "dev")]))
        all_val[name] = {"ids": {vkey(r[k]) for r in rows}, "texts": {norm_text(r["claim"]) for r in rows},
                         "text_required_zero": _treq,
                         "meta": {"sha256": sha256_file(p), "rows": len(rows),
                                  "claim_ids": len({r[k] for r in rows})}}
    v4id = lambda r: "v4-" + r["id"][3:]  # noqa: E731
    s1100 = {v4id(r) for r in conf11}
    t1100 = {norm_text(r["question"]) for r in conf11}
    s300 = {v4id(r) for r in conf11 if r.get("switch_added")}
    t300 = {norm_text(r["question"]) for r in conf11 if r.get("switch_added")}
    sdev = {v4id(r) for r in dev}
    tdev = {norm_text(r["question"]) for r in dev}
    tv4dev = {norm_text(pools[key_of[i]][i]["question"]) for i in v4_dev_ids}
    tv4prim = {norm_text(pools[key_of[i]][i]["question"]) for i in v4_primary_ids}
    nc_v4 = {"v4-" + i[3:] for i in not_collected}
    req = OrderedDict()
    for tag, ids_, txt in (("collect_1100", s1100, t1100), ("reserve_added_300", s300, t300)):
        req[f"{tag}_x_v4_dev_ids"] = len(ids_ & set(v4_dev_ids))
        req[f"{tag}_x_v4_dev_texts"] = len(txt & tv4dev)
        req[f"{tag}_x_v4_primary_ids"] = len(ids_ & set(v4_primary_ids))
        req[f"{tag}_x_v4_primary_texts"] = len(txt & tv4prim)
        req[f"{tag}_x_v4_stage_b_requested_ids"] = len(ids_ & requested)
        req[f"{tag}_x_v5_dev_ids"] = len(ids_ & sdev)
        req[f"{tag}_x_v5_dev_texts"] = len(txt & tdev)
        for name, v in all_val.items():
            req[f"{tag}_x_validation:{name}_ids"] = len(ids_ & v["ids"])
            if v["text_required_zero"]:
                req[f"{tag}_x_validation:{name}_texts"] = len(txt & v["texts"])
    req["collect_1100_x_not_collected_600_ids"] = len(s1100 & nc_v4)
    for name, v in all_val.items():
        req[f"v5_dev_x_validation:{name}_ids"] = len(sdev & v["ids"])
        if v["text_required_zero"]:
            req[f"v5_dev_x_validation:{name}_texts"] = len(tdev & v["texts"])
    req["collect_1100_duplicate_ids"] = len(conf11) - len(set(ids11))
    req["collect_1100_duplicate_texts_within_source"] = sum(
        v - 1 for v in Counter((r["source"]["key"], norm_text(r["question"])) for r in conf11).values() if v > 1)
    bad = {k: v for k, v in req.items() if v}
    if bad:
        raise SystemExit(f"1.1.0 exclusion proof failed: {bad}")
    checks["v1_1_0_exclusions_hold"] = True

    proofs11 = OrderedDict()
    proofs11["build_version"] = BUILD_VERSION_SWITCH
    proofs11["method"] = proofs["method"] + (" Validation ids without the v4- prefix (FEVER slices: fever<id>) are "
                                             "mapped to v4-<id> before intersecting.")
    sets = json.loads(json.dumps(proofs["sets"]))
    sets["checker_validation_all_slices"] = OrderedDict(
        (name, dict(v["meta"], ids_sha256=sha256_ids(v["ids"]), n_distinct_texts=len(v["texts"])))
        for name, v in all_val.items())
    sets["collect_1100"] = {"n": len(ids11), "sorted_ids_sha256": got_hash["sorted_1100"]}
    sets["not_collected_600"] = {"n": len(not_collected), "sorted_ids_sha256": got_hash["sorted_not_collected_600"],
                                 "content": "200 TruthfulQA primary (1.0.0 orders after the stratum) + 400 1.0.0 extension"}
    sets["reserve_added_300"] = {"popqa": {"n": len(add_ids["popqa"]), "first": add_ids["popqa"][0],
                                           "last": add_ids["popqa"][-1], "list_sha256": got_hash["popqa_reserve_0_150"]},
                                 "fever": {"n": len(add_ids["fever"]), "first": add_ids["fever"][0],
                                           "last": add_ids["fever"][-1], "list_sha256": got_hash["fever_reserve_0_150"]}}
    proofs11["sets"] = sets
    proofs11["v4_stage_b"] = stage_b
    proofs11["required_zero"] = req
    proofs11["v1_0_0_required_zero"] = inter
    proofs11["disclosed_not_required_zero"] = OrderedDict([
        ("same_text_collisions_with_later_validation_slices", {
            "n": len(collisions), "n_in_collect_1100": sum(c["in_1_1_0_collect"] for c in collisions),
            "n_in_v5_dev": sum(c["in_v5_dev"] for c in collisions),
            "note": "Different FEVER ids, identical normalised claim text (paper_dev repeats claims). Id-level "
                    "disjointness holds. The 1,100 are fixed by prereg §6.2 hashes, so they are not replaced here; "
                    "the remedy, if wanted, is to re-score the affected validation slice without these pairs "
                    "(no new checker calls).",
            "pairs": collisions}),
        ("collect_1100_from_v4_extension_uncollected", sum(r["v4_tier"] == "extension_uncollected" for r in conf11)),
        ("collect_1100_from_v4_extension_by_source", dict(sorted(Counter(
            r["source"]["key"] for r in conf11 if r["v4_tier"] == "extension_uncollected").items())))])
    proofs11["all_required_zero"] = True

    # ---------------------------------------------------------------- write
    os.makedirs(a.out, exist_ok=True)

    def write(name, b):
        p = os.path.join(a.out, name)
        with open(p, "wb") as f:
            f.write(b)
        return p

    p_dev = write("items_dev.jsonl", b_dev)
    p_conf = write("items_confirmatory.jsonl", ser_jsonl(conf11))
    p_res = os.path.join(a.out, "reserve_order.json")
    if not os.path.exists(p_res) or sha256_file(p_res) != hashlib.sha256(b_res).hexdigest():
        write("reserve_order.json", b_res)              # unchanged from 1.0.0 (prereg §6.3 item 3)
    p_proof = write("exclusion_proofs.json", ser_json(proofs11))

    def comp(rows, f):
        return dict(sorted(Counter(f(r) for r in rows).items()))

    def max_dev(rows, quotas):
        tot, cnt, worst = sum(quotas.values()), Counter(), 0.0
        for n, r in enumerate(rows, 1):
            cnt[r["source"]["key"]] += 1
            worst = max(worst, max(abs(cnt[k] - n * q / tot) for k, q in quotas.items()))
        return round(worst, 4)

    P = [r for r in conf11 if r["tier"] == "primary"]
    T = [r for r in conf11 if r["tier"] == "tqa_stratum"]
    composition = OrderedDict([
        ("dev", comp(dev, lambda r: r["source"]["key"])),
        ("collect_by_tier", comp(conf11, lambda r: r["tier"])),
        ("P_by_source", comp(P, lambda r: r["source"]["key"])),
        ("P_switch_added_by_source", comp([r for r in P if r.get("switch_added")], lambda r: r["source"]["key"])),
        ("T_by_source", comp(T, lambda r: r["source"]["key"])),
        ("strata_dev", comp(dev, lambda r: f"{r['source']['key']}:{r['stratum']}")),
        ("strata_P", comp(P, lambda r: f"{r['source']['key']}:{r['stratum']}")),
        ("strata_P_switch_added", comp([r for r in P if r.get("switch_added")],
                                       lambda r: f"{r['source']['key']}:{r['stratum']}")),
        ("popqa_props_P", comp([r for r in P if r["source"]["key"] == "popqa"], lambda r: r["source"]["prop"])),
        ("tqa_T_type", comp(T, lambda r: r["source"]["type"])),
        ("tqa_T_categories", comp(T, lambda r: r["source"]["category"])),
        ("corpus_routing", comp(dev + conf11, lambda r: f"{r['split']}:{r['corpus']}")),
        ("prefix_max_deviation_items", max_dev(conf11, SWITCH_QUOTAS)),
    ])
    manifest = OrderedDict([
        ("build_version", BUILD_VERSION_SWITCH), ("seed", SEED),
        ("spec", "real-agent-eval/v5/PREREGISTRATION.md §6.1-§6.3 (TruthfulQA quota switch); base draw "
                 "v3/SWARM3_DESIGN.md §4, §6.2, §8 lane L4 (= v5-benchmark-1.0.0, archived in 1.0.0/)"),
        ("switch", OrderedDict([
            ("trigger", "dev TruthfulQA evidence availability 4/22 = 0.18 < 0.30 (prereg §6.1)"),
            ("k", SWITCH_K), ("tqa_stratum_n", TQA_STRATUM_N),
            ("quotas_order", SWITCH_QUOTAS),
            ("streams", {"scifact": "1.0.0 primary order",
                         "popqa": "1.0.0 primary order, then reserve.popqa[0:150]",
                         "fever": "1.0.0 primary order, then reserve.fever[0:150]",
                         "truthfulqa": "first 100 TruthfulQA items of the 1.0.0 primary tier, in order"}),
            ("tiers", {"primary": "P (H1/H2 set), 1,000 items", "tqa_stratum": "T, 100 items (H3b, H4 T-columns, "
                       "descriptive only)", "switch_added": "true on the 300 reserve items"}),
            ("list_sha256", got_hash), ("list_sha256_matches_prereg", True),
            ("n_items_to_collect", len(conf11)),
        ])),
        ("sources", OrderedDict((k, dict(v4_manifest["sources"][k])) for k in SOURCES)),
        ("licence_note", "Item files mix licences: FEVER-derived lines (and the fever17 corpus) CC BY-SA 3.0 "
                         "(share-alike); SciFact claims CC BY 4.0, abstracts ODC-By 1.0; TruthfulQA Apache-2.0; "
                         "PopQA MIT, facts Wikidata CC0."),
        ("pool_accounting_v1_0_0", accounting),
        ("stratification_v1_0_0", strat_notes),
        ("composition", composition),
        ("checks", checks),
        ("inputs", OrderedDict([
            ("v4_manifest.json", sha256_file(v4_manifest_p)),
            ("v4_build_benchmark.py", sha256_file(v4_builder_p)),
            ("v4_items_dev.jsonl", v4_manifest["outputs"]["items_dev.jsonl"]),
            ("v4_items_confirmatory.jsonl", v4_manifest["outputs"]["items_confirmatory.jsonl"]),
            ("v4_conf_run_manifest.json", stage_b["run_manifest_sha256"]),
            ("validation_v1_0_0_draw", val_meta),
            ("validation_all_asserted", OrderedDict((n, v["meta"]) for n, v in all_val.items())),
            ("archived_v1_0_0", OrderedDict((n, sha256_file(os.path.join(archive, n))) for n in sorted(os.listdir(archive))
                                            if os.path.isfile(os.path.join(archive, n)))),
        ])),
        ("outputs", OrderedDict((os.path.basename(p), sha256_file(p)) for p in (p_dev, p_conf, p_res, p_proof))),
        ("script_sha256", sha256_file(os.path.abspath(__file__))),
        ("python", sys.version.split()[0]),
    ])
    write("manifest.json", ser_json(manifest))
    print(json.dumps({"switch_hashes": got_hash, "composition": composition, "checks": checks,
                      "outputs": manifest["outputs"]}, indent=1))


if __name__ == "__main__":
    main()
