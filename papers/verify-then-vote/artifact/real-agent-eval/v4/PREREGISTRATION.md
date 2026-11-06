# Eval v4 preregistration

> **APPROVED 2026-10-21 (gate Q2).** The open decisions were resolved by the analysis team (delegated by the author); the resolutions are recorded at the end of this file and applied in §2 and §5. Frozen per `FREEZE.json`. Freezing means:
>
> 1. the author approves it;
> 2. its sha256, together with the sha256 of `benchmark/items_*.jsonl`, `benchmark/manifest.json`,
>    `benchmark/scripts/answer_key.py` and `canon/canon.py`, is recorded in
>    `real-agent-eval/v4/FREEZE.json`;
> 3. the files are committed.
>
> Changes after the freeze are amendments: dated, appended in §13, and never applied
> retroactively to data already seen.

Author: the analysis team. Date drafted: 2026-10-21. Inputs:

- `real-agent-eval/v3/RESULTS.md` and the `paired_decisions_*.csv` files;
- `v2/bran-paper.md` §9.2–9.2.1, §10–11;
- `real-agent-eval/v4/canon/` (canon-1.0.0);
- `real-agent-eval/v4/power/POWER.md`.

## 1. Background and what changes from v3

Eval v3 found that the implemented reducer did not beat majority vote. Four problems made that
comparison weak:

- **Recency in the tie-break.** Per-dimension Schulze in the deadband votes on recency even at
  weight 0.
- **A degenerate majority baseline.** Majority vote degenerated to first-member because free-text
  objects are paraphrases. The conservative canonicalizer (canon-1.0.0) dissolved 0 of 14
  decisive sets, and majority still equals first-member on 14/14.
- **Author-written gold and unvalidated graders.**
- **Too few decisive conflicts.** v3 had 14 from 13 of 55 questions, about 0.25 per question.

v4 makes four changes:

1. **Borrowed gold.** Items come from TruthfulQA (MC1), PopQA, FEVER and SciFact, with
   ground-truth labels copied mechanically (`benchmark/BENCHMARK.md`).
2. **Answer-constrained collection.** Every prompt asks for the usual free-text answer, with
   sources and confidence, and then a final line `ANSWER: <value>` over a small closed answer
   space: an option letter, SUPPORTED/REFUTED, or a short entity name. This is a new protocol,
   reported as such. It gives each item exactly one functional slot `(v4-<id>, answer, ·)` per
   run, so:
   - majority vote counts real agreement;
   - decisive conflicts are independent across items, so the exact McNemar test is valid
     without clustering;
   - the decisive-conflict yield is expected to rise well above v3's 0.25 per question.
3. **Gold-blind canonicalization of answers** before slotting, for both the reducer and majority
   (§4.2).
4. **Recency-free controls** (§5).

## 2. Hypotheses

**H1 (primary).** On decisive conflicts, the order-free Bran reducer (M3: recency weight 0, recency bit cleared from the Schulze dimensions, `tiebreak_order = id`, deadband kept) selects
the correct answer more often than plurality majority vote over canonicalized answers (M2). The default policy (M1) is not used for H1 because eval v3 showed its tie-break depends on arrival order.

- H0: P(Bran correct, majority wrong) = P(Bran wrong, majority correct).
- The test is two-sided.

**H2 (key secondary, non-inferiority).** The order-free reducer (M3) is not worse than the default
reducer (M1) on decisive conflicts.

- The order-free reducer is: recency weight 0, the recency bit cleared from the Schulze
  dimensions, `tiebreak_order = id`, and the deadband kept.
- H0: acc(recency-free) − acc(default) ≤ −0.10.
- If non-inferiority holds, superiority is tested at the same α (closed testing; no extra α).

**H3 (deferred).** Evidence-support verification improves selection over the same reducer
without verification. H3 is **not** registered here. It requires an amendment, filed before any
verification-enabled analysis of confirmatory data is run. The amendment must define:

- the verification artifacts;
- the H3 contrast;
- its own α = 0.05.

H3 data may reuse the confirmatory responses, because verification is a function of sealed
responses plus captured evidence.

## 3. Units, outcome and primary test

- **Run.** Each item is asked once (R = 1) to each of the 5 agents.
- **Answer slot.** The slot holds the parseable answers of that run (§4.1).
- **Eligible item.** At least 2 parseable answers.
- **Decisive conflict.** An eligible item whose parsed answers contain at least one correct and
  at least one incorrect answer under the primary grader. Every method can then be right or
  wrong. Decisiveness depends only on the members' correctness, not on any method's selection,
  so it is method-blind.
- **Primary outcome.** Correctness (0/1) of each method's selected answer on each decisive
  conflict.
- **Primary test.** The exact two-sided McNemar test (binomial on discordant pairs b, c with
  p = 0.5, p = min(1, 2·min(P(B≤b), P(B≥b)))), at α = 0.05. This is the same definition as
  `evaluate_v3.py`, comparing the order-free Bran reducer (M3) against canonical majority (M2).
  - **Reported with it:** b, c, the accuracy difference (b−c)/N and its 95% CI. The CI is the
    Newcombe hybrid score interval for paired proportions; an item bootstrap with 10,000
    resamples and seed 42 is the cross-check.
- **Why no clustering.** With R = 1 there is at most one decisive conflict per item, and items
  are independent draws from fixed datasets. At R = 1, the power simulations (POWER.md Table 4)
  give a naive exact-test size of 0.034–0.042, so the test is conservative and valid.

### 3.1 Grader: which is primary, and why

**The primary grader is the answer-key grader G-AK** (`benchmark/scripts/answer_key.py:grade`).
It works as follows:

- **MC and binary items:** exact equality of the parsed letter or label with the dataset gold.
  These cover three sources and 75% of items. Grading is deterministic and needs no validation
  beyond the parse audit.
- **PopQA entities:** the published PopQA rule. The answer is correct iff a gold alias appears in
  the ANSWER line on word boundaries.

Neither v3 grader is primary. Both score free-text triples by token overlap and neither is
validated:

- the "original" grader ignores polarity, which is the mechanism that inflated the pilot;
- the "stricter" grader misses numeric paraphrases.

Where v4 still grades free-text triples (secondary S1), **the stricter grader is primary for that
analysis**. It is conservative and polarity-aware, and polarity errors are the known
false-positive mode. The original grader is reported beside it for continuity with v3.

**Human-validated grading.** The author, and ideally a second labeler, label:

- a stratified sample of dev PopQA answers, at least 120 answer lines, before the freeze of the
  confirmatory analysis code (§7 step 3);
- after collection, a blinded sample of confirmatory decisive conflicts, at least 150 items with
  oversampling of PopQA.

We report Cohen's κ (bootstrap CI) between human and G-AK. The primary analysis is then re-run
on the human-labeled subset as a sensitivity analysis, together with the exact-canonical-alias
grader. **The primary grader is never switched after unblinding.**

## 4. Inputs to every method

### 4.1 Parsing

`parse_answer(item, text)` is gold-blind. It takes the last line matching `ANSWER:` (markdown
decoration tolerated).

- **letter:** an option letter in range, or the option whose `canon()` text equals the line.
- **supported_refuted:** {supported, supports, support, true} → SUPPORTED;
  {refuted, refutes, refute, contradict(ed/s), false} → REFUTED. Both or neither → unparseable.
- **entity:** `canon(line)`.

Unparseable answers are dropped from the slot for every method alike, and the drop is counted
per model.

### 4.2 Canonicalization, and how majority is computed

- **Canonicalizer.** The `canon()`, version **canon-1.0.0** (file sha256 recorded at freeze:
  currently `a33b4e338666c0f3a0c774891fcb0a2bc5f4edecdfc67947308cf40b3c5e7bb2`).
  - It is applied to entity answers.
  - Letters and labels are already canonical.
  - It never sees gold. Gold-assisted merging, such as mapping an answer onto the matched alias,
    is forbidden, because it would favour majority by merging only correct variants.
- **Majority (primary baseline).** Plurality over canonical objects among the slot's parsed
  answers.
  - A tie among the top objects is broken uniformly at random with
    `random.Random("v4-majority:" + item_id)`, which is order-free.
  - Secondary variant: ties broken by earliest arrival (the v3 behaviour).

### 4.3 Reducer input

Each parsed answer becomes one contribution:

- **Triple:** `(v4-<id>, answer, <canonical object>)`, `AFFIRM`.
- **Evidence:** the evidence items that the v3 extraction (`evaluate_v2.load_contributions`,
  associate=True) attaches to claims in the same response, de-duplicated by text, with
  `UNVERIFIED` and reachable = true as in v3.
- **Confidence:** parsed exactly as in v3.
- **Lowering confidence:** `HIGH`, because the parse is an explicit line.
- **Seq:** `arrival_seq` × 1000.
- **Policy:** the slot is made exclusive by declaring every observed canonical object of the
  `answer` predicate incompatible. This is the v3 "forced" policy restricted to `answer`, and it
  is gold-blind.
- **Policy hashes:** recorded per variant.

## 5. Methods (all run on identical slots)

| # | method | definition | role |
|---|---|---|---|
| M1 | Bran default | `bran --reduce`, DEFAULT_POLICY of `evaluate_v3.py` (weights .35/.20/.25/.05/.15, deadband 500, Schulze ε 100, all 5 Schulze dims) | H2 |
| M2 | Majority (canonical) | §4.2, seeded-random ties | H1 baseline |
| M3 | Bran order-free Schulze | M1 with recency weight 0, `schulze_dims = 23` (recency bit cleared), `tiebreak_order = id` | H1, H2 |
| M4 | Bran recency 0 + no deadband | weights .35/.20/.25/0/.15, deadband 0 | control |
| M5 | Evidence-only | weights 1/0/0/0/0, deadband 0 | control |
| M6 | Bran score-then-canonical | M4 weights, deadband 500, `tiebreak = score_then_canonical` | control (if the binary at freeze supports it) |
| M7 | Majority, earliest-arrival ties | v3 behaviour | control |
| M8 | First member | earliest arrival | diagnostic |
| M9 | Last member | latest arrival | diagnostic |
| M10 | Random member | `Random("v4-random:" + id)` | chance reference |
| M11 | Best single model | the agent with the highest dev-split accuracy, fixed before confirmatory collection; falls back to M2 if that agent's answer is unparseable | strong baseline |
| M12 | Oracle | 1 on every decisive conflict by definition (reported for scale only) | bound |

## 6. Secondary outcomes (descriptive unless stated)

- **S1. Free-text protocol arm.** Run the v3 pipeline on the same responses, minus the ANSWER
  line: v3 extraction, canon-1.0.0 on objects, then Tables A/B with the stricter grader
  primary. Report M3 vs M2 and M3 vs M1 with exact McNemar. This keeps continuity with v3. The
  primary gold triple only covers the answer slot, so this arm is graded against the readability
  triples (G-POP-2, G-FEV-2, G-TQA-2) and is exploratory.
- **S2.** Accuracy of every method over all eligible items, decisive or not.
- **S3.** Results by source and by PopQA popularity stratum.
- **S4. Separation.** Evidence gap and total-score gap > δ = 0.05 on decisive conflicts.
- **S5. Deadband.** Entry rate, and the share of deadband winners that are the latest arrival.
- **S6.** Per-model accuracy and parse-failure rate.
- **S7.** Grader validation: κ, and the sensitivity analysis of §3.1.
- **S8.** Pairwise comparisons M1 vs each of M3–M11 (exact McNemar). Holm-adjusted p-values are
  reported across this family, as descriptive.

## 7. Collection protocol (two stages, one approval)

1. **Environment.**
   - Models and digests: the five v3 models with identical digests (`v3/results/run_manifest.json`):

     | model | digest |
     |---|---|
     | llama3.2:3b | `a80c4f17…5b8b72` |
     | mistral | `6577803a…c1cf` |
     | gemma2:2b | `8ccf136f…09d7` |
     | phi3:mini | `4f222292…47e9` |
     | qwen2.5:3b | `357c53fb…4b` |

     The collector verifies the digests via `/api/show` at start and aborts on any mismatch.
   - Server: Ollama 0.17.7, recorded. Server env as in v3: `OLLAMA_NUM_PARALLEL=1`, auto max
     loaded models, recorded from the startup log.
   - The machine is quiet: no other agent jobs and no evaluator runs during collection. This
     differs from v3.
2. **Requests.**
   - System prompt: `SYSTEM_PROMPT_V4`, which is the v3 system prompt plus the ANSWER-line
     instruction (exact text in `benchmark/manifest.json`). User prompt: the item's `prompt`
     field, verbatim.
   - Options: temperature 0.7, num_predict 1024, seed 42.
   - All 5 requests per item are dispatched concurrently in an order shuffled by
     `random.Random(dispatch_seed)`, with dispatch seed **20261101**. Items run sequentially in
     frozen `order`.
   - A single lock-protected sequencer assigns `arrival_seq` when each response body has been
     fully read. Raw records keep dispatch order, arrival order, timestamps, `/api/ps` samples
     and errors, exactly as in `v3/collect_v3.py`.
   - Timeout 900 s. A failed request is retried up to 2 times with the same seed, and its
     arrival is the successful attempt's arrival. After 3 failures the answer is missing.
3. **Stage A (dev).**
   1. Collect all 160 dev items.
   2. Use them to audit the parse rules, and to have the author hand-check PopQA entity grading on
      at least 120 answer lines.
   3. If agreement between human and G-AK is below 0.90, `answer_key.py` may be revised
      **once**, using dev evidence only, before step 6.
   4. Compute the pooled yield y_A (decisive conflicts per dev item) and the pooled discordance
      ψ_A between M1 and M2, as b+c only; b−c is not used for any decision.
   5. Pick M11's model.
   6. The analysis team writes and tests `evaluate_v4.py` on dev data. Its sha256 and the revised
      `answer_key.py` hash are recorded in an amendment **before** Stage B starts.
4. **Sample size and stopping rule.** This rule is fixed now and uses only y_A and ψ_A.
   1. Let ψ* = max(ψ_A, 0.25), and let N* be the smallest stable N giving 80% power at Δ = 0.10
      for ψ* (POWER.md Table 1).
   2. Items to collect: I = 4·⌈N*/(4·y_A)⌉, clamped to [600, 1000]. These are the first I items
      of `items_confirmatory.jsonl` in `order`. The tiers are balanced by construction.
   3. If I would exceed 1000, collect 1000 and report the achieved power at Δ = 0.10 and 0.15
      (POWER.md Table 3). No further extension is allowed.
   4. There are **no interim analyses** of confirmatory data. The confirmatory analysis runs once,
      after collection of all I items is complete.
5. **Stage B (confirmatory).** Collect the first I items with the same environment and seeds.
   Dev and confirmatory results are never pooled.

## 8. Exclusions

- **Item-level.** An item is excluded from conflict analysis if fewer than 2 parseable answers
  remain. These items are counted and reported by source.
- **No post hoc item removal.** Gold errors discovered after collection are reported as a
  sensitivity analysis (results with the flagged items removed), not as exclusions.
- **Agent-level.** If any agent's parse failure rate on Stage A exceeds 50%, the ANSWER-line
  wording may be amended once, before Stage B. Otherwise all five agents stay in.
- **Run-level.** No reruns of completed confirmatory items. A crash resumes from the next
  uncollected item, as `collect_v3.py` resume does.

## 9. Multiple comparisons

- The confirmatory family is {H1, H2}, tested in fixed sequence:
  1. H1 at α = 0.05 (two-sided);
  2. only if H1 is rejected, H2 non-inferiority at one-sided α = 0.025, margin −0.10. If that
     holds, H2 superiority is tested at two-sided 0.05.
- If H1 is not rejected, H2 is reported as exploratory, with its p-value and CI but no claim.
- H3 has its own α, by amendment.
- Secondary comparisons (S8) are descriptive, with Holm-adjusted p-values.

## 10. Power (from `power/POWER.md`)

The calculation uses the exact McNemar test with independent decisive conflicts, α = 0.05, and
80% power required to stay ≥ 0.80 for the next 25 values of N. ψ is the discordant-pair rate.
v3 gives ψ = 0.44–0.67 for the default reducer against majority, and 0.11–0.25 for the
recency-free reducer against majority.

| Δ (accuracy diff.) | ψ = 0.25 | ψ = 0.35 | ψ = 0.50 |
|---|---|---|---|
| 0.10 | 207 | 289 | 408 |
| 0.15 | 92 | 129 | 183 |

Items needed are N / yield:

| target | yield 0.255 (v3) | 0.50 | 0.75 | 1.0 |
|---|---|---|---|---|
| Δ = 0.10, ψ = 0.35 | 1,134 | 578 | 386 | 289 |
| Δ = 0.15, ψ = 0.35 | 506 | 258 | 172 | 129 |

The power implication of constrained answers is large. Under the free-text protocol (v3 yield
0.255 per question), detecting a 10-point difference at ψ = 0.35 needs about 1,134 questions,
and at the stricter grader's yield of 0.16 it needs about 1,800. If the ANSWER line raises the
yield to 0.5–0.75, as expected with 5 small models on adversarial or long-tail items, the
600-item primary tier gives:

- for Δ = 0.15: ≥ 0.86 power at any ψ ≤ 0.5;
- for Δ = 0.10: 0.82 (yield 0.5) to 0.94 (yield 0.75) power at ψ = 0.35.

If the yield stays at v3's 0.255, 600 items give only 0.51 power at Δ = 0.10 and 0.87 at
Δ = 0.15 (ψ = 0.35).

The 1,000-item cap gives ≥ 0.80 at Δ = 0.10 for all ψ ≤ 0.5 when the yield is ≥ 0.5. See
POWER.md for the H2 non-inferiority power. With true difference 0 and margin −0.10, power is
0.97 at N = 300 and ψ = 0.2, and 0.83 at ψ = 0.35. With margin −0.05 it is ≤ 0.50 at N = 300
for ψ ≥ 0.2, which is why −0.10 is proposed.

## 11. Analysis code path (to be written by the analysis team; frozen by hash before Stage B)

1. `real-agent-eval/v4/collect_v4.py` is a fork of `v3/collect_v3.py`. It reads
   `benchmark/items_*.jsonl`, uses `SYSTEM_PROMPT_V4`, and writes
   `v4/results/{dev,conf}/raw/<id>.json` plus `run_manifest.json`. The manifest holds digests,
   the Ollama version, the server env, the seeds, the sha256 of the item files, and FREEZE.json.
2. `real-agent-eval/v4/evaluate_v4.py` does the following:
   1. For each item, it calls `answer_key.parse_answer` on every response.
   2. It builds contributions as in §4.3. Evidence comes from
      `evaluate_v2.load_contributions(associate=True)` on the same response.
   3. It runs `bran --reduce` once per policy variant M1, M3, M4, M5 and M6, recording the binary
      sha256, `build_provenance.json` and the policy hashes.
   4. It computes M2 and M7–M12 in Python.
   5. It grades with `answer_key.grade`.
   6. It writes `v4/results/<split>/paired_decisions_v4.csv`, one row per eligible item, with
      columns id, source, stratum, n_parsed, n_correct, decisive, in_deadband, and then M1…M12.
   7. It writes `separation_margins_v4.csv` and `evaluation_v4.json`.
   8. The primary statistic comes from `mcnemar_p` (the v3 definition) on the M1/M2 columns over
      `decisive == 1`, with the Newcombe CI and an item bootstrap (10,000, seed 42).
   9. Separately, it runs the S1 pipeline (v3 extraction + `canon` + `evaluate_v3` table
      builders) on the same raw responses.
3. `real-agent-eval/v4/make_results.py` generates `RESULTS.md`. The order is: preregistered
   analysis first, then deviations from this document, then exploratory analyses.
4. A Python mirror check (as in v3) asserts that the Python re-implementation of selection
   matches the binary on every slot, and the run aborts on mismatch.

## 12. Known limitations accepted in advance

- **The answer line is a new protocol.** It changes what agents produce, and results do not
  transfer automatically to free-text arbitration. The S1 arm addresses this partially.
- **Answer-level evidence is coarse.** Every citation in a response attaches to its single
  answer, and evidence remains UNVERIFIED until H3.
- **Narrow model pool.** One model pool, one sampling seed and one machine.
- **Dataset caveats.**
  - FEVER labels refer to the 2017 Wikipedia.
  - SciFact items include the abstract, so they test reading, not recall.
  - TruthfulQA MC presents the options, which raises agreement relative to free generation.
- **Yield and discordance are unknown until Stage A.** The stopping rule handles this without
  looking at b−c.

## 13. Amendments

### Amendment 1 (2026-10-22): checker acceptance and H3

Filed before any verification-enabled analysis of confirmatory data. No confirmatory responses exist yet. The author approved the decision on 2026-10-22: "SciFact result is good for us".

**1a. Checker acceptance (deviation from the evidence spec §2.2 item 1).**

- **Checker accepted.** `76d44ce22b1ea2f476539e36daacc81a` is accepted on the public SciFact slice alone (`tools/evidence/support/VALIDATION.md`), and may be listed in `accepted_checkers`. The spec asked for a human-labeled slice of v4 captures; that slice is not required for acceptance.
- **Public-slice results.**
  - macro-F1 0.866 (0.829–0.903)
  - `refutes` precision 0.880 (0.811–0.940)
  - injection success 0/50 (Wilson upper bound 7.1%)
  - stability 48/50 (lower bound 86.5%)
- **Thresholds.** All four thresholds pass on the point estimate. The injection and stability CIs do not exclude their thresholds; this is reported as a limitation.
- **Human slice.** If the human slice is labeled later, it is reported as a sensitivity analysis and does not change H3's result.
- **Re-run.** If the checker identity changes (CLI version, model, prompt, flags), the SciFact validation must be re-run before the new `checker_id` is accepted.

**1b. H3 (confirmatory, own α = 0.05).**

- **Hypothesis.** On decisive conflicts (§3), the order-free reducer with evidence verification (M3+E) selects the correct answer at a different rate than the same reducer without it (M3).
- **Test.** Exact two-sided McNemar on the discordant pairs. The unit, gold and grader are the same as for H1. H3 is not part of the H1/H2 closed-testing family and has its own α.
- **M3+E.** M3's policy plus `evidence`, set to the spec §3.4 defaults:
  - support factors: supports 1.0, not_enough_info 0.5, refutes 0.0
  - `unchecked_factor` 1.0
  - `use_support_score` false
  - `legacy_source_xref` false
  - `accepted_checkers = ["76d44ce22b1ea2f476539e36daacc81a"]`
- **Artifacts.**
  - **Capture.** Every evidence identifier extracted from the confirmatory `source_lines` by `tools/evidence/extract.py` is captured once by `tools/evidence/capture.py` under one fixed epoch, and sealed as `bran-capture/1` records.
  - **Support.** `ok` captures are checked by `tools/evidence/support/check.py` and sealed as `bran-support/1` records.
  - **Sealing.** Both sets go into a `bran-artifact/3` evidence store.
  - **Analysis.** It reads only the sealed records. Nothing is re-fetched or re-checked during analysis.
- **Reported alongside (descriptive).**
  - capture outcome rates
  - the share of claims with at least one attached evidence item
  - support label distribution
  - checker refusals (scored as unchecked)
  - M3+E vs M2
- **Low attachment.** If fewer than 10% of decisive items have any checked evidence attached to a candidate, H3 is reported as untestable at this attachment rate rather than as a null.

### Amendment 2 (2026-10-22): contrast used for ψ and the primary statistic

This corrects wording left over from before the resolution of 2026-10-21, which moved H1 to M3 vs M2. It is filed before any Stage B data exist.

- **ψ_A (§7 step 3.4).** The stopping rule uses ψ_A between **M3 and M2**, the H1 pair, not M1 and M2.
- **Primary statistic (§11 item 8).** It is computed on the **M3/M2** columns. `evaluate_v4.py` already does both: `psi_M3_M2` and `H1 = paired(dec, "M3", "M2")`.
- **Size unchanged.** Stage A gives I = 600 under either reading: ψ 0.325 for M3/M2 and 0.3375 for M1/M2 (`results/dev/stage_a_v4.json`).
- **M1/M2.** It stays a descriptive pair inside S8.

### Amendment 3 (2026-10-22): PopQA check before Stage B, code freeze, sensitivity analysis

This amendment is filed before any Stage B data exist. The author delegated the decision to an independent model review: Claude Opus 5.5 and OpenAI Codex were each asked separately, and both chose the same option.

- **PopQA hand-check moved after Stage B.** The §7 step 3.2 hand-check of G-AK on at least 120 PopQA dev answer lines is **not** done before Stage B.
  - `answer_key.py` is frozen unrevised: the once-only revision of §7 step 3.3 is waived. Its sha256 is unchanged at `b3ffdbae…`.
  - No model labels substitute for the human check.
  - Human validation of G-AK is done only after collection, on the blinded sample of at least 150 confirmatory items in §3.1. It is reported as κ with a sensitivity analysis.
  - The paper states that G-AK's PopQA grading had no human validation before the confirmatory run.
- **Pre-declared sensitivity analysis S9.** H1, H2 and H3 are repeated on the decisive conflicts from the three exact-match sources (TruthfulQA MC, FEVER, SciFact), with PopQA excluded. These are computed from the frozen per-item output table, and the reduced power is disclosed. The primary analysis remains the full set.
- **Code freeze (§7 step 3.6).** The following are added to `FREEZE.json`:
  - `collect_v4.py` `19f212e6…`
  - `evaluate_v4.py` `755d4399…`
  - the evaluation binary, sha256 `43c55b36…`, built at commit 9e27f29
  - M11 = `qwen2.5_3b` (Stage A)
- **Size.** I = 600 (Amendment 2).

### Amendment 4 (2026-10-22): simulated-labeler check of PopQA grading

The author asked for the PopQA hand-check of §7 step 3.2 to be done by models simulating human annotators. It ran before any Stage B grading; Stage B collection was in progress and does not depend on the check. This replaces the "moved after Stage B" item of Amendment 3. The rest of Amendment 3 stands.

- **Labelers.** Claude Opus 5.5 (`claude -p`, high effort) and OpenAI Codex (`codex exec`, high reasoning) each labelled all 169 rows of `results/dev/popqa_label_sheet.csv` independently. They were blind to G-AK verdicts and used the same written rubric (`results/dev/popqa_sim/label_prompt.md`). The labels are in `results/dev/popqa_sim/`.
- **Results.**
  - Opus vs G-AK: 162/169 agreement (0.959), κ = 0.917.
  - Codex vs G-AK: the same.
  - Opus vs Codex: 169/169 agreement.
- **Threshold met.** 0.959 ≥ 0.90, so the §7 step 3.3 revision is not triggered and `answer_key.py` stays frozen.
- **Disagreements (7 rows).**
  - 6 are G-AK false positives, where a gold alias appears inside a wrong answer, for example "Newcastle" in "Newcastle upon Tyne".
  - 1 is a false negative: "Jane Randolph" for gold "Jane Randolph Jefferson".
  - These are reported as a known bias of the published PopQA rule.
- **Disclosure.** These are model labels standing in for a human, not human labels. The two labelers agreeing perfectly may reflect correlated judgment rather than accuracy. The paper reports them as simulated-annotator validation.
- **What stays.** The post-collection blinded sample of §3.1 and sensitivity analysis S9 are unchanged.

### Amendment 5 (2026-10-22): non-inferiority to majority vote (H4) and cost of arbitration (S10)

This amendment was filed while Stage B collection was in progress (about 200 of 600 items collected). No confirmatory response, selection or grade has been read or analysed. It follows the author's decision to frame the paper around whether a minimal, deterministic arbitration step costs anything relative to majority vote, as well as whether it beats it.

- **H4 (confirmatory, own α).** On decisive conflicts, the order-free reducer (M3) is not worse than canonical majority (M2) by more than 10 points.
  - H0: acc(M3) − acc(M2) ≤ −0.10.
  - Rejected iff the lower bound of the two-sided 95% Newcombe hybrid score interval for the paired difference exceeds −0.10. This is one-sided α = 0.025. The unit, gold and grader are those of H1.
  - H4 is outside the H1/H2 family and is not used to rescue H1. The paper reports H1, the two-sided superiority test, as it falls. H4 states only whether a deficit larger than 10 points is excluded.
  - Failing to reject H1 together with rejecting H4 is reported as "no detectable difference; a deficit greater than 10 points is excluded". It is never reported as equivalence.
  - H4 is computed from the frozen per-item output table with the same `newcombe_paired` function as H2.
- **S10 (descriptive): cost of arbitration.**
  - **Arbitration time.** Wall-clock time of the frozen reducer binary per item, measured by replaying each sealed confirmatory reduction after collection on an otherwise idle machine. Reported as median and 95th percentile, and as a fraction of that item's agent generation time from the raw records.
  - **Size overhead.** The size of the sealed input and certificate relative to the raw responses.
- **Pre-declared exploratory conditions.**
  - M3 − M2 accuracy on decisive conflicts split by whether score separation (S4) holds.
  - The same split by whether any candidate has checked evidence attached (H3 data).
  - These are descriptive, with no inferential claim.

### Amendment 6 (2026-10-22): dev-data deviation and analysis hold

- **Deviation on dev data.** While planning a follow-up study (v5), its design work computed majority-vote accuracy on the 160 dev items. §7 allows only yield and discordance on dev. The figures were used only to size v5, and no v4 rule, item, grader or analysis choice was changed afterwards. The deviation is disclosed here and in the paper.
- **Analysis hold.** Confirmatory evaluation (`evaluate_v4.py --split conf`) is not run, and confirmatory responses are not graded, until the v5 preregistration is frozen. This keeps the v5 design independent of v4's confirmatory results. Collection still completes on schedule, and the sealed raw records are not read for accuracy before the hold lifts.

## Resolved questions (2026-10-21, delegated by the author)

Resolutions: (1) H1 tests M3, the order-free reducer, against M2; M1 enters only H2 and S8. (2) H2 margin −0.10 accepted. (3) The answer-line protocol is primary; free text is secondary arm S1. (4) If dev yield is low, extend items (R = 1); no seed replication. (5) Second labeler: none confirmed; κ is human-vs-grader only unless one is added before Stage B. (6) FEVER CC BY-SA 3.0 accepted; FEVER-derived item files carry that licence and are distributed separately from the code. (7) Downloaded datasets are not committed; hashes and fetch commands are (`benchmark/manifest.json`).

Original questions as drafted:

1. **H1 arm.** H1 tests the default policy, the system the paper describes. Should H1 instead
   test the recency-free reducer (M3), the configuration the paper will probably recommend? The
   draft keeps the default for H1 and puts M3 in H2.
2. **H2 margin.** The non-inferiority margin is −0.10 (−0.05 is underpowered; see POWER.md).
3. **Answer line as primary.** Should the answer-constrained protocol be primary, with the
   free-text protocol as the secondary arm S1? The draft says yes.
4. **Replication versus more items.** If dev yield is low, should we collect R = 3 seeds per item
   and use the Durkalski clustered McNemar test instead of more items? The draft says no
   (R = 1, extend items).
5. **Second labeler.** Is a second labeler available for κ (gate Q4)?
6. **FEVER share-alike.** Is CC BY-SA 3.0 on the FEVER-derived item files acceptable for the
   paper artifact?
