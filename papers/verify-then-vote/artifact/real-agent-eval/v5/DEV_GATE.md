# Eval v5 dev gate (G4)

Status: dev only, 2026-10-22. Nothing here touches confirmatory data, and nothing in
`real-agent-eval/v4/results/conf/` was read. Dev accuracy is reported because this is the dev gate
and the v5 prereg is not frozen yet. It must not be pooled with confirmatory data.

**Recommendation: proceed with the grounded fleet. The mixed-fleet fallback is not indicated.
The pre-declared §2.2 TruthfulQA switch is triggered.** Yield and majority-wrong share both pass
with room to spare. TruthfulQA fails evidence availability (18% against a 30% threshold). Two
issues should be settled before the freeze (§5): H2 looks unwinnable as designed, and the FEVER
checker validation misses the refutes-precision threshold.

## 1. Gate table (design §6.2)

| check | dev value | threshold | result | if it fails |
|---|---|---|---|---|
| yield y_dev (decisive / items) | **86 / 160 = 0.538** | ≥ 0.30 | pass | mixed-fleet arm |
| majority-wrong share m_dev (decisive) | **26 / 86 = 0.302** (0.306 with the tie-break expectation) | ≥ 0.20 | pass | mixed-fleet arm |
| evidence availability, TruthfulQA | **4 / 22 = 0.18** | ≥ 0.30 | **fail** | §2.2 TQA switch |
| evidence availability, PopQA | 9 / 16 = 0.56 | ≥ 0.30 | pass | |
| evidence availability, FEVER | 17 / 19 = 0.89 | ≥ 0.30 | pass | |
| evidence availability, SciFact | 27 / 29 = 0.93 | ≥ 0.30 | pass | |
| parse failure, worst agent | 0 / 160 for all five | < 5% | pass | one schema fix |

G4 in the design's words: on dev, **30% of disagreements had the majority wrong**, and **107 of
160 items (67%) still had a real disagreement** (≥ 2 distinct canonical answers; 86 of them decisive).
Grounding did not make everyone agree.

How evidence availability was measured: an item counts if some agent's shown top-5 holds a passage
that the accepted checker labels `supports` for the gold value.

- **TruthfulQA and PopQA.** The gold proposition was checked against every passage shown on each
  decisive item, so coverage is 100%. As a cross-check for PopQA, a gold alias appears as a whole
  word in a shown passage on 13 of 16 items (0.81). That match is a heuristic, not a support check.
- **FEVER and SciFact.** For cost reasons the gold claim was checked only on cited passages and on
  passages that are gold evidence by the item's own ids (FEVER sentence ids within the passage's
  `sent_ids` range; SciFact evidence doc ids). The evaluator therefore marks these two figures as
  lower bounds. The deterministic check without the LLM gives the same picture: FEVER 17 / 19
  (16 / 19 when a full evidence set must be covered), SciFact 27 / 29.
  (`results/dev/gold_availability_deterministic.json`)

Stopping rule: ψ_dev = 0.291 for the selected BE, so N\* = 426 decisive conflicts.
I = ⌈426 / 0.538⌉ = 793, clamped to **I = 1,000**, which is the planned size.

## 2. BE configuration (design §5.1), selected on dev

| config | b | c | b − c | ψ | changed fields |
|---|---|---|---|---|---|
| member/nei0.5 | 15 | 8 | 7 | 0.267 | 0 |
| **member/nei0.1** | **17** | **8** | **9** | 0.291 | 1 |
| value:max/nei0.5 | 15 | 8 | 7 | 0.267 | 1 |
| value:max/nei0.1 | 17 | 9 | 8 | 0.302 | 2 |
| value:pooled/nei0.5 | 14 | 8 | 6 | 0.256 | 1 |
| value:pooled/nei0.1 | 15 | 10 | 5 | 0.291 | 2 |

**Selected: `member/nei0.1`.** `policy_template_sha256` is
`d135c367f6cbe512…` (the full hashes of all 6 configurations are in `results/dev/eval/evaluation_v5.json`
→ `BE_grid`). The margin over the runner-up is a single item. The selection is therefore close to
noise, but it follows the pre-declared rule.

## 3. Dev results on the 86 decisive conflicts (descriptive)

| method | accuracy | b vs MAJ | c vs MAJ |
|---|---|---|---|
| MAJ | 0.698 | | |
| BEST (mistral) | 0.663 | 14 | 17 |
| B0 | 0.558 | 7 | 19 |
| **BE** | **0.802** | **17** | **8** |
| EO | 0.791 | 16 | 8 |
| VV | 0.826 | 11 | 0 |
| J | 0.965 | 23 | 0 |
| RS | 0.977 | 24 | 0 |
| ORC | 1.000 | 26 | 0 |

- **BE vs MAJ.** b = 17, c = 8, net gain +0.105 (Newcombe 95% CI −0.008 to 0.215). Exact McNemar
  p = 0.108 at n = 86.
  - p̂_w = 0.65 (Wilson 0.46–0.81) and q̂_r = 0.13 (0.07–0.24). Both are above the planning
    values (0.4 and 0.10).
- **BE vs J.** BE trails J by 0.163 (Newcombe −0.253 to −0.089), so non-inferiority fails clearly
  on dev. J never overturned a right majority.
- **By source** (BE vs MAJ, b / c):

  | source | b / c | BE accuracy | MAJ accuracy |
  |---|---|---|---|
  | SciFact | 8 / 0 | 0.97 | 0.69 |
  | PopQA | 5 / 1 | 0.81 | 0.56 |
  | FEVER | 2 / 1 | 0.89 | 0.84 |
  | TruthfulQA | 2 / 6 | 0.50 | 0.68 |

- **Replay and checks.** BE replay was byte-identical on 160 / 160 items. The Python mirror matched
  the binary on all 1,280 reducer slots. S4 separation held on 18 / 86 decisive items.
- **Check labels.** 1,127 de-duplicated checks: 1,125 `ok` and 2 refused (SciFact, sealed as
  `parse_error`). Of the ok labels, 896 are NEI (80%), 143 supports and 86 refutes.
  - On TruthfulQA, 195 of 212 cited checks are NEI. The gold proposition is supported on only 1 of
    273 shown-passage checks, because FEVER-2017 lead sections rarely address misconceptions.
- **Parse audit.** All 800 answers parsed, with no truncations and 100% valid citations
  (`results/dev/parse_audit.json`).

## 4. FEVER validation of the checker

The slice has 300 pairs (100 supports, 100 refutes, 100 NEI) and a 50-pair regeneration. The
checker is `76d44ce22b1ea2f476539e36daacc81a`. Report:
`tools/evidence/support/validation/76d44ce22b1ea2f476539e36daacc81a.fever.json`.

How the slice was drawn:

- It excludes all 347 v5 FEVER ids (dev + confirmatory) and all v4 FEVER items, 591 ids in total.
  The overlap is asserted to be zero.
- Supports and refutes pairs take claims from the tail of `reserve_order.json`'s FEVER list. Each
  is paired with the fever17 passage that contains its first single-page evidence set.
- NEI pairs are paper_dev NEI claims (seeded shuffle, 20261022), each paired with its BM25 top-1
  passage.

| metric | FEVER | SciFact (accepted) | threshold | FEVER pass |
|---|---|---|---|---|
| macro-F1 | 0.839 (0.796–0.878) | 0.866 | ≥ 0.70 | yes, including the CI lower bound |
| refutes precision | **0.788 (0.713–0.860)** | 0.880 | ≥ 0.80 | **no** |
| supports precision | 0.862 | 0.923 | — | |
| regeneration stability | 49 / 50 = 0.98 (0.895–0.997) | 0.96 | ≥ 0.95 | yes on the point estimate |

All 25 refutes false positives are explained by two sources. 21 of them come from NEI pairs. The
other 4 are supports claims, which gives 93 / 97 = 0.96 refutes precision on the supports and
refutes classes alone. In the NEI misses, the checker reads a passage's silence as a contradiction:
for example, "Blade Runner 2049 stars Keanu Reeves" against a cast list without him. FEVER calls
this NEI. The behaviour hits passages that are on-topic but incomplete, and agents see many of
those. A refutes label zeroes the citation, so the error can only remove support, never add it. q_r
is driven by false supports, and the FEVER slice gives 13 / 100 NEI→supports. The author must
decide whether this is acceptable, since it fails the pre-set threshold (§5).

## 5. Design issues found

1. **H2 is very likely to fail.** J reaches 0.965 and RS 0.977 on decisive dev. Sonnet 5.5
   answers FEVER, SciFact and TruthfulQA almost perfectly, possibly from training exposure (design
   §7.3). Also, on decisive items J's allowed values always include a correct one. The design's
   "H1 positive, H2 fails" row should be expected. The paper framing should lean on H3 (replay and
   audit) and BE vs MAJ, not on parity with J.
2. **What drives c (right majorities overturned) is citation volume, not checker false positives.**
   All 8 BE c-cases (6 TruthfulQA, 1 PopQA, 1 FEVER) were won by a minority agent whose citations
   were all NEI: one agent citing 1–3 NEI passages beats majority members who cite nothing. In
   member mode headcount does not count, and NEI still earns 0.1 per citation. Two variants would
   address this, but the grid does not contain them: an NEI factor of 0, or requiring a `supports`
   label to overturn. VV does exactly the second and gets c = 0, b = 11. Decide before the freeze
   whether to extend the grid. Changing it after seeing dev is a disclosed design change.
3. **The checker costs about 4.5× the design estimate.** A support check costs about $0.0045, not
   $0.0010. The CLI writes each new user prompt into a 1-hour prompt cache (`cache_creation`
   ≈ 750 tokens per call), and only exact repeats are cheap. J costs $0.014 per item and RS $0.017.
   - Confirmatory at 1,000 items, on the dev ratio of 7 checks per item including the gold-shown
     checks: checks ≈ $30. Add J and RS on about 540 decisive items (≈ $17) and the 200-item J
     regeneration (≈ $3), and the total is **≈ $50**. That is over the $30–40 envelope, so G3 needs
     re-approval.
   - Gold-shown checks on TruthfulQA and PopQA are the largest discretionary item. Restricting
     FEVER and SciFact gold checks to deterministic gold passages, as done here, already saves about
     a third.
4. **The FEVER refutes-precision miss (§4) affects the TruthfulQA switch decision only weakly.**
   It does bear on whether the FEVER control measures c fairly.
5. **CLI version drift.** The checker was validated on Claude Code 2.1.306, and these runs used
   2.1.307. The CLI version is recorded but is not part of `checker_id`.
6. **RS is run on decisive items only.** Its `accuracy_eligible` (0.525) in `evaluation_v5.json`
   is an artifact, because missing RS rows are scored wrong. Use decisive figures only, or run RS on
   all eligible items in confirmatory.

## 6. Cost and time

| step | calls | USD | wall |
|---|---|---|---|
| support checks (1,127 distinct + 25 retried or aborted-run calls) | 1,152 | 5.37 | ≈ 11 min (6 workers) |
| judge J (86 decisive) | 86 | 1.19 | ≈ 2 min (3 workers) |
| reader RS (86 decisive) | 86 | 1.47 | ≈ 2 min |
| FEVER validation (300 + 50 regeneration) | 350 | 1.48 | ≈ 4 min |
| cost diagnosis (2 manual calls) | 2 | < 0.01 | |
| **total dev** | **1,676** | **≈ $9.52** | ≈ 20 min of model time; captures 19 s; evaluate 12 s |

## 7. Files

- **Frozen code for this gate.** `results/dev/dev_code_manifest.json` records the sha256 of the
  judge, its templates and pins, `check.py`, `propositions.py`, `corpus_capture.py`,
  `evaluate_v5.py` and the reducer binary `8f883e3e…`.
  - These were recorded before any model call at HEAD `b37096d`.
  - One amendment is logged there: driver-only changes after the first 103 checker calls.
- **Inputs.** `results/dev/captures.jsonl` (1,915 corpus captures, all `ok`), `checks_plan.jsonl`,
  `checks.jsonl`, `check_calls.jsonl`, `judge_inputs*.jsonl`, `judge-store/`, `judge.jsonl`,
  `decisive_ids.txt`, `parse_audit.json`, `gold_availability_deterministic.json`.
- **Evaluation.** `results/dev/eval/` (`evaluation_v5.json`, `dev_gate_v5.json`,
  `paired_decisions_v5.csv`, `overturns_v5.jsonl`, `rust/`).
- **Driver.** `tools/evidence/support/run_checks_v5.py`; tests in
  `tools/evidence/support/tests/test_run_checks_v5.py` (9 tests, stub CLI).
