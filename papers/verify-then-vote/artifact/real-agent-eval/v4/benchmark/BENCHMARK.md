# Eval v4 benchmark — candidate items, DRAFT pending gate Q2

Built by `scripts/build_benchmark.py` (seed 20261021, `v4-benchmark-1.0.0`) from four published
datasets. **Every gold answer is copied from the source dataset.** Nothing is author-written, and
no model output was used to select items: no responses have been collected.

Rebuild (byte-identical outputs; hashes in `manifest.json`):

```
python3 -I real-agent-eval/v4/benchmark/scripts/build_benchmark.py \
  --downloads real-agent-eval/v4/benchmark/downloads --out real-agent-eval/v4/benchmark
python3 -I real-agent-eval/v4/benchmark/scripts/answer_key.py --selftest
```

`downloads/` holds the raw files. They are data only: nothing in them is executed, and the build
script reads them by path under `python3 -I`. Per-file sha256 values are in `manifest.json`.
TLS downloads worked normally on this host, with no certificate errors and no verification
overrides.

## Sources and licenses

| key | dataset | version pinned | license | eligible | used (dev + primary + extension) |
|---|---|---|---|---|---|
| truthfulqa | TruthfulQA MC1 (Lin et al. 2022) | git `d71c110` (Jan-2025 revision, 790 q) | Apache-2.0 | 741 | 40 + 150 + 100 |
| popqa | PopQA (Mallen et al. 2023) | git `8172ab0` = HF sha `098765c` (byte-identical) | MIT (repo; HF card states none); facts from Wikidata, CC0 | 1,214 | 40 + 150 + 100 |
| fever | FEVER 1.0 paper_dev (Thorne et al. 2018) | paper_dev.jsonl, sha256 in manifest | Wikipedia copyright policy / **CC BY-SA 3.0** (share-alike applies to the item files) | 6,505 | 40 + 150 + 100 |
| scifact | SciFact (Wadden et al. 2020), train + dev claims | release/latest data.tar.gz, sha256 in manifest | claims **CC BY 4.0**; abstracts **ODC-By 1.0** (S2ORC) | 693 | 40 + 150 + 100 |

The item files therefore mix licenses. If they are redistributed (for example in a paper
artifact), the FEVER-derived lines are CC BY-SA 3.0, and SciFact claims and abstracts need
attribution.

## Splits

- `items_dev.jsonl`: **160 items** (40 per source). This held-out split is used for grader
  development, the parse-rule audit, and yield/discordance calibration (PREREGISTRATION.md §7).
  These items are never part of the confirmatory analysis.
- `items_confirmatory.jsonl`: **1,000 items** in a frozen order. The sources are interleaved
  round-robin, so every prefix is balanced across sources (and, within PopQA, across
  popularity strata). The `tier` field is:
  - `primary` for the first 600 (150 per source);
  - `extension` for orders 600–999, which are collected only under the stopping rule.

  Unused eligible items (the "reserve" counts in `manifest.json`) are not part of v4.

## Eligibility rules (mechanical)

- **TruthfulQA.** Keep `mc_task.json` items whose question is in the current `TruthfulQA.csv`
  and whose `mc1_targets` has exactly one true option. Drop context-dependent or time-sensitive
  categories:
  - Indexical Error: Location (11), Identity (8) and Other (18);
  - Subjective (9);
  - Misconceptions: Topical (3).

  Options are shuffled once per item with `Random("20261021:truthfulqa:<id>")`, and the
  shuffled order is frozen in the prompt.
- **PopQA.** Keep only single-valued relations: place of birth, father, mother, capital, and
  country. "capital of" is dropped as multi-valued. Also drop:
  - questions that occur more than once in PopQA (78; multi-valued in the dataset itself);
  - subjects with `s_pop < 1000` monthly views (1,532). These are mostly ambiguous names
    ("In what country is Tina?") or facts no 3B model knows. All-wrong items cannot be decisive.

  The remaining items are stratified by popularity into [1e3, 1e4), [1e4, 1e5) and ≥ 1e5, with
  50/50/50 in the primary tier. The relation mix in the primary tier is capital 70, father 28,
  country 24, place of birth 14 and mother 14.
- **FEVER.** Keep SUPPORTS/REFUTES and drop NOT ENOUGH INFO. Drop claims with time-sensitive
  tokens (years 2015–2029, current/currently, still, now, as of, recent(ly), latest, upcoming,
  will, this year: 161). The prompt asks for the truth value "according to Wikipedia as of
  2017", matching the dump the labels were made against.
- **SciFact.** Keep claims with rationale evidence, all of whose evidence labels agree (no
  mixed-label claim exists in train + dev). The prompt includes the lowest-id evidence
  abstract, because the gold label is defined relative to an abstract and not to "the
  literature". SciFact test labels are hidden, so test claims are not used.

Primary-tier gold balance:

- FEVER: 81 SUPPORTED, 69 REFUTED;
- SciFact: 96 SUPPORTED, 54 REFUTED;
- TruthfulQA: 2 to 12 options (median 5).

## Item fields

Each item records:

- `id`;
- `source`: dataset key, source id, and per-source metadata such as category, s_pop/stratum,
  Wikidata URIs or label;
- `item_type`, `question`, `options` (MC), `context` (SciFact abstract);
- `prompt`: the exact user prompt;
- `system_prompt`: the name of `SYSTEM_PROMPT_V4`, whose text is in `manifest.json`;
- `answer_format`: `letter`, `supported_refuted` or `entity`;
- `gold`: answer and aliases;
- `gold_triples`: each with its derivation rule;
- `predicate_type`: always `functional`;
- `contested_rationale`, `review_note`, `split`, `tier` and `order`.

### Gold-triple derivations

Each item's graded triple is `(v4-<id>, answer, <gold>)` on the functional predicate `answer`.
The derivation rule is one of:

- **G-TQA-1:** the letter of the unique MC1-true option after the frozen shuffle.
- **G-POP-1:** the PopQA `obj`; accepted aliases are `possible_answers`, verbatim.
- **G-FEV-1:** the FEVER label, SUPPORTS→SUPPORTED and REFUTES→REFUTED.
- **G-SCI-1:** the SciFact rationale label, SUPPORT→SUPPORTED and CONTRADICT→REFUTED.

The readability triples G-TQA-2, G-POP-2 and G-FEV-2 are not graded. No item needed a manual
review note except the PopQA source-level note: Wikidata aliases are incomplete or noisy, and
that is audited on dev.

### Why "contested"

These rationales are priors from the source papers, not measurements, because no v4 responses
exist yet:

- **TruthfulQA:** adversarial imitative-falsehood questions with the dataset's own distractors.
- **PopQA:** small-LM accuracy falls steeply with entity popularity (Mallen et al.), so a
  mid-popularity band should split a 5-model pool.
- **FEVER:** REFUTES claims are plausible mutations of true sentences.
- **SciFact:** CONTRADICT claims are negated or altered findings that need careful reading.

The dev split measures the actual yield per source and stratum.

## Answer protocol and grader (`scripts/answer_key.py`)

The free-text v3 protocol produced paraphrased objects that canonicalization cannot merge (canonicalization
canon-1.0.0 dissolved 0 decisive v3 sets, and majority = first-member on 14/14). Every v4 prompt
therefore ends with a structured final line, `ANSWER: <value>`, over a small closed answer space
(a letter, SUPPORTED/REFUTED, or a short entity name). The free-text body is kept for
evidence/citation extraction.

- `parse_answer(item, text)` is **gold-blind**. It uses the last `ANSWER:` line and returns:
  - **letter:** an option letter, or the option whose canonical text equals the line;
  - **SUPPORTED/REFUTED:** by keyword set, or None if both or neither appear;
  - **entity:** `canon()` from `real-agent-eval/v4/canon/canon.py`, canon-1.0.0, sha256
    `a33b4e33…e7bb2`.

  Its output is the object passed to the reducer and to majority vote.
- `grade(item, obj, raw_line)` uses gold:
  - letter and label items: exact equality;
  - entity items, primary: the published PopQA rule (an alias appears in the answer line on
    word boundaries);
  - entity items, secondary: exact canonical alias match.
