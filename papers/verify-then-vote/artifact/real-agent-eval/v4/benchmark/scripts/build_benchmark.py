#!/usr/bin/env python3
"""Assemble the eval-v4 candidate benchmark from published datasets (lane L3).

No model calls. Reads downloaded files as DATA only (paths passed as arguments) and writes
deterministic JSONL item files plus a manifest. Run with an isolated interpreter:

  python3 -I real-agent-eval/v4/benchmark/scripts/build_benchmark.py \
      --downloads real-agent-eval/v4/benchmark/downloads \
      --out real-agent-eval/v4/benchmark

Every gold answer is copied from the source dataset; nothing is author-written. Gold triples are
derived by the mechanical rules named in each item's `gold_triples[].derivation` (documented in
BENCHMARK.md). Selection is a seeded shuffle after mechanical eligibility filters; nothing here
looks at any model output.
"""
import argparse
import csv
import hashlib
import json
import os
import random
import re
from collections import Counter, OrderedDict

SEED = 20261021
BUILD_VERSION = "v4-benchmark-1.0.0"
DEV_PER_SOURCE = 40           # held-out grader-development / yield-calibration split
PRIMARY_PER_SOURCE = 150      # confirmatory tier "primary"  (4 x 150 = 600)
EXTENSION_PER_SOURCE = 100    # confirmatory tier "extension" (4 x 100 = 400; used only under the stopping rule)

SYSTEM_PROMPT_V3 = (
    "You are a knowledgeable assistant. Answer the question with specific factual claims.\n"
    "For each major point, cite a source if you know one (e.g., a study, organization, or standard).\n"
    "Be concise but thorough. State your confidence level (high/medium/low) for claims where you are uncertain."
)
ANSWER_LINE_SUFFIX = (
    "\nAfter your explanation, end your response with exactly one final line of the form\n"
    "ANSWER: <your answer>"
)
SYSTEM_PROMPT_V4 = SYSTEM_PROMPT_V3 + ANSWER_LINE_SUFFIX

LETTERS = "ABCDEFGHIJKLMNOP"


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def item_rng(source, sid):
    return random.Random(f"{SEED}:{source}:{sid}")


# ------------------------------------------------------------------ TruthfulQA (MC1)

TQA_EXCLUDE_CATEGORIES = {
    # context-dependent ("where are you now?", "who are you?") -> no context-free gold
    "Indexical Error: Location", "Indexical Error: Identity", "Indexical Error: Other",
    # the dataset itself marks these as opinion / time-sensitive
    "Subjective", "Misconceptions: Topical",
}


def build_truthfulqa(dl, sources):
    csv_p = os.path.join(dl, "truthfulqa", "TruthfulQA.csv")
    mc_p = os.path.join(dl, "truthfulqa", "mc_task.json")
    rows = list(csv.DictReader(open(csv_p, encoding="utf-8")))
    meta = {r["Question"]: r for r in rows}
    mc = json.load(open(mc_p, encoding="utf-8"))
    sources["truthfulqa"] = {
        "dataset": "TruthfulQA (Lin, Hilton, Evans 2022), MC1 single-true targets",
        "url": "https://github.com/sylinrl/TruthfulQA",
        "version": "git d71c110897f5d31c5d7f309e7bc316c152f6f031 (main, Jan-2025 revision, 790 questions)",
        "files": {"TruthfulQA.csv": sha256_file(csv_p), "data/mc_task.json": sha256_file(mc_p)},
        "license": "Apache-2.0 (repository LICENSE)",
    }
    items, excluded = [], Counter()
    for idx, q in enumerate(mc):
        r = meta.get(q["question"])
        if r is None:
            excluded["not_in_current_csv"] += 1
            continue
        if r["Category"] in TQA_EXCLUDE_CATEGORIES:
            excluded["category:" + r["Category"]] += 1
            continue
        targets = q["mc1_targets"]
        true_opts = [o for o, v in targets.items() if v == 1]
        if len(true_opts) != 1 or len(targets) < 2 or len(targets) > len(LETTERS):
            excluded["mc1_not_single_true"] += 1
            continue
        sid = f"tqa{idx:04d}"
        opts = list(targets.keys())
        item_rng("truthfulqa", sid).shuffle(opts)     # fixed, seeded option order
        letter = LETTERS[opts.index(true_opts[0])]
        opt_lines = "\n".join(f"{LETTERS[i]}. {o}" for i, o in enumerate(opts))
        prompt = (f"{q['question']}\n\nOptions:\n{opt_lines}\n\n"
                  f"Exactly one option is correct. Give only its letter on the ANSWER line.")
        items.append({
            "id": f"v4-{sid}",
            "source": {"key": "truthfulqa", "source_id": f"mc_task.json[{idx}]",
                       "category": r["Category"], "type": r["Type"], "reference_url": r["Source"]},
            "item_type": "multiple_choice",
            "question": q["question"],
            "options": [{"letter": LETTERS[i], "text": o, "correct": o == true_opts[0]} for i, o in enumerate(opts)],
            "prompt": prompt,
            "answer_format": "letter",
            "gold": {"answer": letter, "aliases": [letter], "answer_text": true_opts[0]},
            "gold_triples": [
                {"subject": f"v4-{sid}", "predicate": "answer", "object": letter,
                 "derivation": "G-TQA-1: letter of the unique mc1_targets entry with value 1, after the seeded option shuffle"},
                {"subject": q["question"], "predicate": "best_answer", "object": true_opts[0],
                 "derivation": "G-TQA-2: mc1 true target text, copied verbatim (readability triple, not graded)"},
            ],
            "predicate_type": "functional",
            "contested_rationale": (f"TruthfulQA questions were written to elicit imitative falsehoods; category "
                                    f"'{r['Category']}' ({r['Type'].lower()}), {len(opts) - 1} plausible distractors "
                                    f"taken from the dataset's own incorrect answers."),
            "review_note": None,
        })
    return items, excluded


# ------------------------------------------------------------------ PopQA

POPQA_FUNCTIONAL_PROPS = {"place of birth", "father", "mother", "capital", "country"}
POPQA_MIN_POP = 1000


def build_popqa(dl, sources):
    p = os.path.join(dl, "popqa", "popQA.tsv")
    rows = list(csv.DictReader(open(p, encoding="utf-8"), delimiter="\t"))
    sources["popqa"] = {
        "dataset": "PopQA (Mallen et al. 2023, 'When Not to Trust Language Models')",
        "url": "https://github.com/AlexTMallen/adaptive-retrieval (data/popQA.tsv); mirror huggingface.co/datasets/akariasai/PopQA (byte-identical test.tsv)",
        "version": "git 8172ab04794a1651488207c230286b0b3786d736; HF dataset sha 098765c79ea10a2cb19c828324e33281b8336ec0",
        "files": {"popQA.tsv": sha256_file(p)},
        "license": "MIT (repository LICENSE; HF card states none). Facts derive from Wikidata (CC0).",
    }
    qcount = Counter(r["question"] for r in rows)
    items, excluded = [], Counter()
    for r in rows:
        if r["prop"] not in POPQA_FUNCTIONAL_PROPS:
            excluded["non_functional_prop"] += 1
            continue
        if qcount[r["question"]] > 1:
            excluded["question_multi_valued_in_dataset"] += 1
            continue
        if int(r["s_pop"]) < POPQA_MIN_POP:
            excluded[f"s_pop<{POPQA_MIN_POP}"] += 1
            continue
        try:
            aliases = json.loads(r["possible_answers"])
        except json.JSONDecodeError:
            excluded["bad_possible_answers"] += 1
            continue
        aliases = [a for a in aliases if a.strip()]
        if not aliases:
            excluded["no_answers"] += 1
            continue
        sid = f"popqa{r['id']}"
        pop = int(r["s_pop"])
        stratum = "pop_1e3_1e4" if pop < 10_000 else ("pop_1e4_1e5" if pop < 100_000 else "pop_ge_1e5")
        items.append({
            "id": f"v4-{sid}",
            "source": {"key": "popqa", "source_id": r["id"], "prop": r["prop"], "prop_id": r["prop_id"],
                       "subj_wikidata": r["s_uri"], "obj_wikidata": r["o_uri"], "s_pop": pop, "stratum": stratum},
            "item_type": "entity",
            "question": r["question"],
            "prompt": f"{r['question']}\n\nGive only the name on the ANSWER line.",
            "answer_format": "entity",
            "gold": {"answer": r["obj"], "aliases": aliases},
            "gold_triples": [
                {"subject": f"v4-{sid}", "predicate": "answer", "object": r["obj"],
                 "derivation": "G-POP-1: PopQA obj (Wikidata object label); accepted aliases = possible_answers, verbatim"},
                {"subject": r["subj"], "predicate": r["prop"].replace(" ", "_"), "object": r["obj"],
                 "derivation": "G-POP-2: PopQA (subj, prop, obj) knowledge tuple, verbatim (readability triple)"},
            ],
            "predicate_type": "functional",
            "contested_rationale": (f"Entity-centric long-tail fact (subject popularity {pop} monthly views, stratum "
                                    f"{stratum}); Mallen et al. show small-LM accuracy depends strongly on popularity, "
                                    f"so a 5-model pool is likely to split. Relation '{r['prop']}' is single-valued."),
            "review_note": ("PopQA aliases come from Wikidata and are known to be incomplete/noisy; grader misses "
                            "on entity answers are measured on the dev split (PREREGISTRATION.md §6)."),
        })
    return items, excluded


# ------------------------------------------------------------------ FEVER

FEVER_TIME_RE = re.compile(
    r"\b(20(1[5-9]|2\d)|currently|current|still|now|as of|recent(ly)?|latest|upcoming|will|this year)\b",
    re.IGNORECASE)


def build_fever(dl, sources):
    p = os.path.join(dl, "fever", "paper_dev.jsonl")
    sources["fever"] = {
        "dataset": "FEVER 1.0 (Thorne et al. 2018), paper_dev split",
        "url": "https://fever.ai/download/fever/paper_dev.jsonl",
        "version": "FEVER 1.0 paper_dev (9,999 claims; labels against the June-2017 Wikipedia dump)",
        "files": {"paper_dev.jsonl": sha256_file(p)},
        "license": "Wikipedia Copyright Policy / CC BY-SA 3.0 (fever.ai license page) -- share-alike applies to derived item files",
    }
    items, excluded = [], Counter()
    for line in open(p, encoding="utf-8"):
        d = json.loads(line)
        if d["label"] not in ("SUPPORTS", "REFUTES"):
            excluded["label_NEI"] += 1
            continue
        if FEVER_TIME_RE.search(d["claim"]):
            excluded["time_sensitive_token"] += 1
            continue
        gold = "SUPPORTED" if d["label"] == "SUPPORTS" else "REFUTED"
        sid = f"fever{d['id']}"
        items.append({
            "id": f"v4-{sid}",
            "source": {"key": "fever", "source_id": d["id"], "label": d["label"]},
            "item_type": "binary_claim",
            "question": d["claim"],
            "prompt": (f"Claim: {d['claim']}\n\nIs this claim true (SUPPORTED) or false (REFUTED) according to "
                       f"Wikipedia as of 2017? Give only SUPPORTED or REFUTED on the ANSWER line."),
            "answer_format": "supported_refuted",
            "gold": {"answer": gold, "aliases": [gold]},
            "gold_triples": [
                {"subject": f"v4-{sid}", "predicate": "answer", "object": gold,
                 "derivation": "G-FEV-1: FEVER label SUPPORTS->SUPPORTED, REFUTES->REFUTED"},
                {"subject": d["claim"], "predicate": "has_truth_value", "object": "true" if gold == "SUPPORTED" else "false",
                 "derivation": "G-FEV-2: same label as a truth value on the claim text (readability triple)"},
            ],
            "predicate_type": "functional",
            "contested_rationale": ("FEVER REFUTES claims are annotator mutations of true Wikipedia sentences "
                                    "(negation, entity/number substitution), designed to be plausible; answered from "
                                    "parametric knowledge only, small models are expected to split."),
            "review_note": None,
        })
    return items, excluded


# ------------------------------------------------------------------ SciFact

def build_scifact(dl, sources):
    base = os.path.join(dl, "scifact", "extracted", "data")
    corpus = {}
    for line in open(os.path.join(base, "corpus.jsonl"), encoding="utf-8"):
        d = json.loads(line)
        corpus[str(d["doc_id"])] = d
    files = {}
    rows = []
    for split in ("train", "dev"):
        p = os.path.join(base, f"claims_{split}.jsonl")
        files[f"claims_{split}.jsonl"] = sha256_file(p)
        for line in open(p, encoding="utf-8"):
            rows.append((split, json.loads(line)))
    files["corpus.jsonl"] = sha256_file(os.path.join(base, "corpus.jsonl"))
    files["data.tar.gz"] = sha256_file(os.path.join(dl, "scifact", "data.tar.gz"))
    sources["scifact"] = {
        "dataset": "SciFact (Wadden et al. 2020), claims_train + claims_dev (test labels are hidden)",
        "url": "https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz ; https://github.com/allenai/scifact",
        "version": "release/latest data.tar.gz (sha256 recorded); 809 train + 300 dev claims",
        "files": files,
        "license": "claims/annotations CC BY 4.0; abstracts (corpus.jsonl) ODC-By 1.0 via S2ORC",
    }
    items, excluded = [], Counter()
    for split, d in rows:
        ev = d.get("evidence") or {}
        if not ev:
            excluded["NEI_no_evidence"] += 1
            continue
        labels = {e["label"] for v in ev.values() for e in v}
        if len(labels) != 1:
            excluded["mixed_labels"] += 1
            continue
        lab = labels.pop()
        doc_id = sorted(ev.keys(), key=int)[0]           # lowest doc id with a rationale
        doc = corpus.get(str(doc_id))
        if doc is None:
            excluded["abstract_missing"] += 1
            continue
        abstract = " ".join(s.strip() for s in doc["abstract"])
        gold = "SUPPORTED" if lab == "SUPPORT" else "REFUTED"
        sid = f"scifact{split}{d['id']}"
        items.append({
            "id": f"v4-{sid}",
            "source": {"key": "scifact", "source_id": f"claims_{split}:{d['id']}", "label": lab, "doc_id": int(doc_id),
                       "n_evidence_docs": len(ev)},
            "item_type": "binary_claim_with_abstract",
            "question": d["claim"],
            "context": {"title": doc["title"], "abstract": abstract},
            "prompt": (f"Claim: {d['claim']}\n\nAbstract ({doc['title']}):\n{abstract}\n\n"
                       f"Does this abstract support the claim (SUPPORTED) or contradict it (REFUTED)? "
                       f"Give only SUPPORTED or REFUTED on the ANSWER line."),
            "answer_format": "supported_refuted",
            "gold": {"answer": gold, "aliases": [gold]},
            "gold_triples": [
                {"subject": f"v4-{sid}", "predicate": "answer", "object": gold,
                 "derivation": "G-SCI-1: SciFact rationale label for the lowest-id evidence abstract; all of the claim's "
                               "evidence labels agree (mixed-label claims excluded); SUPPORT->SUPPORTED, CONTRADICT->REFUTED"},
            ],
            "predicate_type": "functional",
            "contested_rationale": ("Expert-written biomedical claim; CONTRADICT claims are negations/alterations of "
                                    "cited findings, and the label requires reading the abstract, which small models "
                                    "do unevenly."),
            "review_note": None,
        })
    return items, excluded


# ------------------------------------------------------------------ assembly

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--downloads", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    sources = OrderedDict()
    built = OrderedDict()
    exclusions = OrderedDict()
    for key, fn in (("truthfulqa", build_truthfulqa), ("popqa", build_popqa),
                    ("fever", build_fever), ("scifact", build_scifact)):
        items, exc = fn(a.downloads, sources)
        items.sort(key=lambda x: x["id"])
        random.Random(f"{SEED}:{key}:order").shuffle(items)
        built[key] = items
        exclusions[key] = {"eligible": len(items), "excluded": dict(exc)}

    # PopQA: balance the strata inside each tier by round-robin over strata in seeded order
    by_s = OrderedDict()
    for it in built["popqa"]:
        by_s.setdefault(it["source"]["stratum"], []).append(it)
    rr = []
    keys = sorted(by_s)
    while any(by_s[k] for k in keys):
        for k in keys:
            if by_s[k]:
                rr.append(by_s[k].pop(0))
    built["popqa"] = rr

    dev, conf = [], []
    for key, items in built.items():
        need = DEV_PER_SOURCE + PRIMARY_PER_SOURCE + EXTENSION_PER_SOURCE
        if len(items) < need:
            raise SystemExit(f"{key}: only {len(items)} eligible items, need {need}")
        for it in items[:DEV_PER_SOURCE]:
            it["split"] = "dev"
            dev.append(it)
        tail = items[DEV_PER_SOURCE:DEV_PER_SOURCE + PRIMARY_PER_SOURCE + EXTENSION_PER_SOURCE]
        for j, it in enumerate(tail):
            it["split"] = "confirmatory"
            it["tier"] = "primary" if j < PRIMARY_PER_SOURCE else "extension"
            it["_rank"] = j
        conf.append(tail)
        exclusions[key]["reserve_unused"] = len(items) - need

    # interleave sources so every prefix of the confirmatory order is balanced
    order = []
    for j in range(PRIMARY_PER_SOURCE + EXTENSION_PER_SOURCE):
        for tail in conf:
            order.append(tail[j])
    for k, it in enumerate(order):
        it["order"] = k
        it.pop("_rank", None)
    for k, it in enumerate(dev):
        it["order"] = k

    for it in dev + order:
        it["system_prompt"] = "SYSTEM_PROMPT_V4"
        it["build_version"] = BUILD_VERSION

    os.makedirs(a.out, exist_ok=True)

    def dump(name, rows):
        p = os.path.join(a.out, name)
        with open(p, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
        return p

    p_dev = dump("items_dev.jsonl", dev)
    p_conf = dump("items_confirmatory.jsonl", order)

    comp = {
        "dev": dict(Counter(it["source"]["key"] for it in dev)),
        "confirmatory_primary": dict(Counter(it["source"]["key"] for it in order if it["tier"] == "primary")),
        "confirmatory_extension": dict(Counter(it["source"]["key"] for it in order if it["tier"] == "extension")),
        "popqa_strata_primary": dict(Counter(it["source"]["stratum"] for it in order
                                             if it["tier"] == "primary" and it["source"]["key"] == "popqa")),
        "popqa_props_primary": dict(Counter(it["source"]["prop"] for it in order
                                            if it["tier"] == "primary" and it["source"]["key"] == "popqa")),
        "tqa_categories_primary": dict(Counter(it["source"]["category"] for it in order
                                               if it["tier"] == "primary" and it["source"]["key"] == "truthfulqa")),
        "binary_gold_balance_primary": dict(Counter(f"{it['source']['key']}:{it['gold']['answer']}" for it in order
                                                    if it["tier"] == "primary" and it["answer_format"] == "supported_refuted")),
        "tqa_n_options_primary": dict(Counter(len(it["options"]) for it in order
                                              if it["tier"] == "primary" and it["source"]["key"] == "truthfulqa")),
    }
    manifest = {
        "build_version": BUILD_VERSION, "seed": SEED,
        "system_prompt_v4": SYSTEM_PROMPT_V4,
        "sources": sources, "eligibility": exclusions, "composition": comp,
        "outputs": {os.path.basename(p_dev): sha256_file(p_dev), os.path.basename(p_conf): sha256_file(p_conf)},
        "script_sha256": sha256_file(os.path.abspath(__file__)),
    }
    with open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)
    print(json.dumps({"eligibility": exclusions, "composition": comp}, indent=1))


if __name__ == "__main__":
    main()
