# Eval v5 preregistration: verify, then vote

> **STATUS: DRAFT, NOT FROZEN (2026-10-22).** Drafted by the analysis team. The freeze
> happens only when all of the following are true:
>
> 1. every `[[LOCAL-ARM: …]]` slot below is filled, or the local arm is dropped to exploratory under
>    §2.3 (this completion is part of drafting and is **not** an amendment);
> 2. every item in the §15 pre-freeze checklist is done, and its hash is in `FREEZE.json` → `sha256`;
> 3. the author approves this document and accepts checker 0.2.0 (§5.3);
> 4. the sha256 of this file is recorded in `real-agent-eval/v5/FREEZE.json`, and the files are committed.
>
> Until then `FREEZE.json` is a draft. It deliberately leaves `benchmark/items_confirmatory.jsonl`
> out of `sha256`, so `collect_v5.py --split conf` refuses to start (§12.2). Changes after the freeze
> are amendments: dated, appended in §16, and never applied retroactively to data already seen.

Author: the analysis team. Inputs: `v3/DESIGN.md` (the design), `v3/FRAMING.md` (the framing,
adopted by the author: "verify, then vote"), `v3/PREREG_DECISIONS.md`, `v3/GATE_SPEC.md`,
`v3/evidence-corpus-addendum.md`, `real-agent-eval/v5/DEV_GATE.md`, the dev outputs in
`results/dev/` (checker 0.1.0) and `results/dev_checker2/eval/` (checker 0.2.0),
`tools/evidence/support/VALIDATION.md`, `benchmark/README.md`, `benchmark/reserve_order.json`,
`power/POWER.md`, `README.md` and `evaluate_v5.py`. Nothing under `real-agent-eval/v4/results/conf/`
was read. No model was called for this document.

## 1. Background and what changes from the design

Eval v4 asks whether a deterministic reducer beats majority vote when agents answer from memory. Its
citations mostly do not resolve, so a verifier has almost nothing to check. Eval v5 builds the regime
where evidence should matter:

- five small agents retrieve from one fixed, hashed corpus;
- they may cite only passages they were shown;
- a checker labels each cited (proposition, passage) pair once, and the label is sealed;
- a frozen rule arbitrates over the sealed labels.

The dev gate (G4) passed on yield (0.538) and majority-wrong share (0.302). TruthfulQA failed
evidence availability (0.18 < 0.30), which triggers the pre-declared TruthfulQA switch (§6).

Dev also showed two things that change the study (disclosed in §13):

- **Ungated evidence weighting can overturn right majorities through NEI-citation volume.** Every
  ungated c-case on dev was won by a minority whose citations were all NEI.
- **Restricting overturns to checker-verified candidates removes that failure.** We adopt this as
  the primary method, under the framing "verify, then vote": a frozen rule may overturn the majority
  only through a verified answer. This bounds harm by checker false supports (`v3/GATE_SPEC.md` §3).

The design's H2 (BE non-inferior to a Sonnet judge) is **deleted**. It is unwinnable (dev: −0.198,
Newcombe −0.29 to −0.12 under checker 0.2.0). We pre-declare that the Sonnet judge J is expected to
exceed every Bran configuration. J, RS and the closed-book Sonnet are upper references only (§2.4).

## 2. Hypotheses

**Analysis sets.**

- **P (primary).** Decisive conflicts (§3) among the 1,000 primary non-TruthfulQA items, which are
  SciFact, PopQA and FEVER after the switch (§6).
- **T (TruthfulQA no-coverage stratum).** Decisive conflicts among the 100 TruthfulQA stratum items.
- P and T are never pooled for any confirmatory test. A pooled table is descriptive only.

**Methods named in the hypotheses** (full definitions in §5):

| name | definition | `policy_template_sha256` |
|---|---|---|
| BE-G | gated reducer `member/nei0.5/gated`, hosted checker 0.2.0 | `99c8b9c91c27d4fcf8cb33be2f342eb6dffa175f10802459df52a23ee2a0a245` |
| BE | ungated reducer `member/nei0.1`, hosted checker 0.2.0 | `084ecdbdcd06193beab228fc9ca21fcf1842f1fffd0326052c5b8908581dada0` |
| BE-G-L | BE-G's configuration with the local checker | `[[LOCAL-ARM: template sha256]]` |
| MAJ | plurality over canonical answers, seeded-random ties (v4 M2) | n/a |
| J_local | local judge | `[[LOCAL-ARM: judge_id]]` |

### 2.1 H1, primary family (Holm, family-wise α = 0.05)

**H1a (primary).** On P, BE-G is correct at a different rate than MAJ.

- H0: P(BE-G right, MAJ wrong) = P(BE-G wrong, MAJ right).
- Exact two-sided McNemar on the discordant pairs (b, c).

**H1b (co-primary).** On P, BE is correct at a different rate than MAJ. Same test.

**Holm procedure.**

1. Order the two p-values, p(1) ≤ p(2).
2. Reject the hypothesis with p(1) iff p(1) ≤ 0.025.
3. Only if step 2 rejects, reject the other iff p(2) ≤ 0.05.

A rejection is read as "better" only if b > c; a rejection with b < c is reported as "worse".

**Reported with each test:**

- b, c, the accuracy difference (b − c)/N;
- the Newcombe hybrid-score 95% CI for the paired difference, and an item bootstrap (10,000
  resamples, seed 42) as a cross-check;
- p̂_w = b/#(MAJ wrong) and q̂_r = c/#(MAJ right), with Wilson 95% CIs.

### 2.2 H3, no-harm (each test has its own α; outside the H1 family)

**H3a (primary sources).** On the items of P where MAJ is right (n_R), let c = #(BE-G wrong).

- H0: q_r(BE-G) ≥ 0.05.
- Reject iff the one-sided 97.5% Clopper–Pearson upper bound on c/n_R is below 0.05 (one-sided
  α = 0.025).
- At the expected n_R ≈ 373, this needs c ≤ 10. Power is 0.95 at q_r = 1/60 (dev) and 0.87 at 0.02.

**H3b (TruthfulQA stratum).** On T, BE-G is non-inferior to MAJ with margin −0.03.

- H0: acc(BE-G) − acc(MAJ) ≤ −0.03.
- Reject iff the lower bound of the two-sided 95% Newcombe interval exceeds −0.03 (one-sided
  α = 0.025).
- **Power warning, pre-declared.** T has about 55 decisive conflicts. Simulation with MAJ accuracy
  0.68 gives power ≈ 0.81 if BE-G and MAJ never disagree on T, ≈ 0.31 at b = c = 2%, and ≈ 0.08 at
  dev's rate (c = 1/22, b = 0). A non-rejection of H3b is therefore reported as "not shown", never as
  harm, unless the point estimate is negative. The margin is kept as FRAMING §3.1 proposed.

**Ungated BE** is reported on the same two tests, descriptively, with the same statistics.

### 2.3 H2, key secondary: the local arm (fixed sequence, own α = 0.05)

**CONDITIONAL.** H2 is confirmatory only if the local checker passes the binding validation criteria
below **before the freeze**. It is being validated in parallel.

- **Binding criteria** (FRAMING §3.2): supports precision ≥ 0.85 on both validation slices,
  macro-F1 ≥ 0.70, and regeneration stability ≥ 0.95.
- **Slices.** FEVER fresh (`validation/fever_slice_fresh2.jsonl`, sha256 `4f83adc0…`) and SciFact-300
  (`validation/slice.jsonl`, `eae58b73…`). Injection success is reported but is not binding.
- **If it fails**, H2 is dropped to exploratory before the freeze, with the text "not run as
  confirmatory; local checker unvalidated". The headline is then H1a/H3 with the hosted checker
  (§14 row 3). The local checks may still be run and reported as exploratory.

**Resolution at freeze (2026-10-22): H2 is EXPLORATORY.** The local checker failed validation. Under the rule above, H2 is "not run as confirmatory; local checker unvalidated". The headline is H1a and H3 with the hosted checker (§14 row 3).

- **Checker that failed:** `mistral:latest`, digest `6577803a…bfbc1cf`, checker_id `41b9f3ecf79bc1917a2b661fb6f521ba`.
- **Its validation report:** `tools/evidence/support/validation/41b9f3ecf79bc1917a2b661fb6f521ba.json`, sha256 `5e7a9f9738507953…`.
- **Results:**

  | slice | metric | result | binding threshold |
  |---|---|---|---|
  | FEVER fresh | macro-F1 | 0.548 | ≥ 0.70 |
  | FEVER fresh | supports precision | 0.774 | ≥ 0.85 |
  | SciFact-300 | supports precision | 0.568 | ≥ 0.85 |
  | — | injection success | 42% | not binding |
  | — | stability | 100% | ≥ 0.95 |

- **Exploratory local runs, reported separately and labelled as such:**
  - **MiniCheck.** `bespoke-minicheck:7b` may be validated after collection on the same slices. If it meets the binding criteria above, BE-G-L and VV-L are reported with it as exploratory. The confirmatory family does not change in any case.
  - **J_local.** The `mistral:latest` judge J-M (`tools/judge/local_judge.py` sha256 `3a3264997cb4f251…`, `prompt_J.txt` unchanged) runs on all disagreement items as an exploratory same-class baseline.
- **Slots.** The slots below are kept as a record and are not filled.

Slots to fill before the freeze. Filling them is not an amendment.

- `[[LOCAL-ARM: checker identity — checker_id, model and digest, backend, local_pin.json sha256, local_check.py sha256, checker_tool_version]]`
  (candidate under validation: `mistral:latest` digest `6577803a…c1cf`, temperature 0, seed 42,
  num_ctx 8192, the 0.2.0 prompt unchanged; candidate id `41b9f3ecf79bc1917a2b661fb6f521ba`)
- `[[LOCAL-ARM: validation results — report path and sha256; FEVER-fresh and SciFact-300 supports precision, macro-F1, stability, injection; PASS/FAIL]]`
- `[[LOCAL-ARM: BE-G-L policy_template_sha256]]` (with candidate id 41b9f3ec…:
  `634eafecd1f1ff8a2df4c7c365139e19f101b9b36169a9c9f45317a672ba8cce`; recompute after the id is final)
- `[[LOCAL-ARM: J_local identity — judge_id, model and digest, local_judge.py sha256, local pin sha256, prompt_J.txt sha256 (must be unchanged 38bc4bfd…)]]`
  (candidate: `mistral:latest`, the participant agent, FRAMING's J-M)
- `[[LOCAL-ARM: driver — the local-checker path through run_checks_v5.py (or its successor), sha256]]`

**Tests, in fixed sequence, each step only if the previous one rejects:**

1. **H2a.** On P, BE-G-L vs MAJ, exact two-sided McNemar at α = 0.05.
2. **H2b-NI.** On P, BE-G-L is non-inferior to J_local with margin −0.05. Reject iff the Newcombe 95%
   lower bound exceeds −0.05 (one-sided α = 0.025).
3. **H2b-S.** BE-G-L vs J_local superiority, exact two-sided McNemar at α = 0.05.

**Diagnostics required for J_local:**

- **Self-preference.** If J_local is a participant model (mistral), report its rate of selecting its
  own agent's answer against the other judges' rate on the same items (Panickssery et al. 2024).
- **Shared model.** If the local checker, J_local and an agent are all mistral, the paper says so in
  the H2 paragraph.

VV-L (VV with local labels) is descriptive.

### 2.4 References and baselines (no confirmatory claim)

- **J** (Sonnet judge) and **RS** (Sonnet reader) are upper references. We make no non-inferiority
  or parity claim against them, and we pre-declare that J > BE-G is expected.
- **CB-S** (closed-book Sonnet: question and options only) quantifies memorisation of these public
  benchmarks (FRAMING O2).
- **CV** (cite vote) and **CONF** (confidence-weighted vote) are cheap baselines. CV isolates
  *verification* from *citing*.
- All four are reported against MAJ and BE-G on P and T with exact McNemar, descriptively.

### 2.5 H4, gate soundness (proved, then checked)

- **Theorem** (`v3/GATE_SPEC.md` §3, Lean statement §4). If D, the reducer's own deterministic
  plurality default, is correct and the gated winner is not, then some incorrect value carries an
  accepted `supports` label. Hence c_D ≤ F.
  - F = #{decisive items where some incorrect value carries an accepted `supports` label}.
  - c_D = #{D correct, BE-G wrong}.
- **Proof status.** The Lean proof is not written yet. The paper says "proved" only if it is
  machine-checked before submission; otherwise it says "proved on paper, mechanisation pending".
- **Checked.** On P and T separately we report:
  - c_D, F, and c against MAJ;
  - the F items, and whether every c_D item is an F item (`harm_bound_holds`). It must hold by
    construction; a violation is reported as an implementation defect and is not re-analysed;
  - **F̂, predicted from validation.** F̂ = Σ over decisive items of 1 − Π(1 − r), where the product
    runs over the checked (incorrect value's proposition, cited passage) pairs of the item. r is the
    pooled non-supports→supports rate of the accepted checker's validation report. For 0.2.0 it is
    (1 + 10 FEVER + 7 SciFact) / (200 + 150) = 18/350 = 0.0514, using FEVER fresh refutes and NEI
    plus SciFact fresh NEI.
  - We report F against F̂ as "validation metrics predict deployment harm", descriptively.
- **Known gap.** On tied-plurality items D can differ from MAJ, so c against MAJ can exceed F without
  any false support (GATE_SPEC §3, caveat 1). It is reported separately.

### 2.6 H5, descriptive

- Gap-closed fraction (§7).
- The cost, latency, replay and audit table, and the accuracy–$ Pareto figure.
- BE-G vs VV and BE vs EO, expected to be close and reported as such.
- Majority-following of every judge.
- By source, by PopQA popularity stratum, and SciFact REFUTED as a subgroup.

## 3. Units, outcome and tests

- **Run.** R = 1. Each item is asked once to each of the five agents.
- **Eligible item.** At least 2 parsed answers.
- **Disagreement item.** At least 2 distinct canonical parsed answers. It is the unit of the uniform
  cost basis (§7).
- **Decisive conflict.** An eligible item with at least one correct and one incorrect parsed answer
  under G-AK. It is method-blind.
- **Primary outcome.** Correctness (0/1) of each method's selected answer on each decisive conflict.
- **Exact McNemar.** p = min(1, 2·min(P(B ≤ b), P(B ≥ b))), B ~ Binom(b + c, ½). This is the
  `mcnemar_p` of v3, v4 and `evaluate_v5.py`.
- **Newcombe interval.** `newcombe_paired` (method 10 hybrid score).
- **No clustering.** With R = 1 there is at most one decisive conflict per item, and items are
  independent draws (v4 §3).
- **Grader.** G-AK (`v4/benchmark/scripts/answer_key.py`, sha256 `b3ffdbae…`), unchanged, so no LLM
  is in the grading loop. Its known PopQA bias stands: 6 false positives in 169 against simulated
  annotators (v4 Amendment 4).

## 4. Inputs to every method

### 4.1 Agent protocol (as dev, `README.md` and design §3)

- Five models with the digests in `v3/results/run_manifest.json`: llama3.2:3b, mistral, gemma2:2b,
  phi3:mini, qwen2.5:3b. The embedder is nomic-embed-text.
- Temperature 0.7, seed 42, dispatch seed 20261101, num_ctx 4096, Ollama 0.17.7,
  `OLLAMA_NUM_PARALLEL=1`, and a quiet machine.
- **Query turn.** Question only, MC options hidden, at most 12 words, num_predict 32.
- **Retrieval.**
  - fever17 (TruthfulQA, PopQA, FEVER): BM25, k = 5.
  - SciFact: BM25 or dense by `Random("v5-ret:"+id)`.
  - Sealed as `bran-retrieval/1`.
- **Answer turn.** Ollama structured output (`schema/answer_v5.schema.json`), citations restricted to
  the labels shown (at most 3), num_predict 512.
- **Arm.** The grounded fleet. The mixed-fleet arm is not used, because the dev gate passed on yield
  and m.

### 4.2 Parsing, canonicalization and MAJ (as dev, `PREREG_DECISIONS.md`)

- **Parse rule.** A response is parsed iff its answer field is valid.
  - A confidence outside the enum counts as "low".
  - A citation to an unshown label becomes an `invalid_identifier` dead capture.
- **Canonicalizer.** canon-1.0.0 (`v4/canon/canon.py`, `a33b4e33…`), gold-blind.
- **MAJ.** Plurality over canonical answers, ties broken by `Random("v5-majority:"+id)`.

### 4.3 Lowering and evidence (`evaluate_v5.py` docstring, design §3.3–§3.4)

- **Contribution.** One AFFIRM triple `(v5-<id>, answer, <canonical value>)` per parsed answer.
  - `raw_text` = the §3.4 proposition (`propositions.py`, renderer 1.0.0).
  - Confidence high .85 / medium .65 / low .45; calibration 0.7; seq = arrival_seq·1000.
  - One CITATION item (weight 1.0) per cited passage, with `capture_ref` and `support_ref`.
- **Captures.** Corpus captures (`bran-capture/1`, `corpus_capture.py`, `ok_rule`
  `corpus-nonempty/1`), sealed in a `bran-artifact/3` store.
- **Support labels.**
  - Value-level, mapped: for binary REFUTED items, `supports` and `refutes` are swapped.
  - Checks are de-duplicated by (proposition, passage_key).
  - The checker never sees other answers, vote counts or gold.
- **Grounded policy.** `unchecked_factor` 0.5. Support factors: supports 1.0, refutes 0.0, NEI per
  configuration. `accepted_checkers` = [the arm's checker id].
- **Policy identity.** Policies are frozen by `policy_template_sha256` per configuration, never by
  `policy_hash`, which varies per item (PREREG_DECISIONS).

## 5. Methods (all run on identical slots)

### 5.1 Method table

| id | method | role |
|---|---|---|
| MAJ | §4.2 | H1, H2a, H3 baseline |
| **BE-G** | `member/nei0.5/gated` (§5.2), hosted checker | **H1a**, H3, H4 |
| **BE** | `member/nei0.1`, ungated, hosted checker | **H1b**; H3 descriptive |
| BE-G-L | BE-G's configuration with the local checker | H2 (conditional) |
| B0 | order-free reducer without the evidence policy (v4 M3); template `e08f2ea6…` | isolates the policy |
| EO | evidence-only weights (1,0,0,0,0), deadband 0, at BE's mode and NEI; template `75ee3a54…` | do the other four features matter |
| VV / VV-L | plurality among answers with ≥ 1 accepted `supports` citation, else MAJ; ties by `Random("v5-vv:"+id)` | one-line verified rule |
| D | the reducer's own plurality default (`gate.default_winner`) | H4 diagnostic |
| CV | plurality among answers citing ≥ 1 passage, any label, unverified; ties by `Random("v5-cv:"+id)`; MAJ if none cites | citing vs verifying |
| CONF | per value, sum of members' confidence weights (.85/.65/.45); argmax; ties by `Random("v5-conf:"+id)` | standard cheap baseline |
| BEST | the agent **mistral**, fixed on dev (`BEST_agent`); MAJ if its answer is unparsed | strong single model |
| J | Sonnet judge, judge_id `4f8c27d90e3c1230dd9b9a91d30530f1` | upper reference |
| RS | Sonnet reader over the union of shown passages, judge_id `108a3dee08e1b4286ea879ee070ce4bb` | upper reference |
| CB-S | Sonnet closed-book: question and options only, constrained to the item's `answer_schema`, graded by G-AK directly; judge_id `[[PENDING: CB-S judge_id]]` | memorisation reference |
| J_local | local judge, `prompt_J.txt` unchanged, num_ctx 8192, temperature 0, fixed seed | H2b (conditional) |
| ORC | 1 on every decisive conflict | bound |

**Judge rules (PREREG_DECISIONS).**

- J sees parsed answers, each agent's confidence and its cited passages. It does not see reasoning or
  model names.
- J's output is constrained to the proposed values. Single-value items are `forced` with no call, and
  BE's cost accounting counts them the same way.
- A null J or J_local decision falls back to MAJ and is counted. Sensitivity analysis: scored wrong.
- A null RS or CB-S answer is scored wrong.
- J, RS and CB-S may use outside knowledge.

### 5.2 Selection of BE-G and BE (dev, checker 0.2.0)

Both selections use the dev grid re-scored with checker 0.2.0 `f2a14bd8…` on all 86 dev decisive
conflicts (`results/dev_checker2/eval/evaluation_v5.json`, sha256 `e111a4b0…`). Old-checker grids
(`results/dev/eval`, `results/dev/eval_gate`) are superseded and are not used for selection.

**BE-G (FRAMING §3.4 rule within the 9 gated templates).** Largest dev (b − c) against MAJ, then
smaller c, then fewer changed fields, then full-grid order.

| gated config | b | c | b − c | changed | template sha256 |
|---|---|---|---|---|---|
| **member/nei0.5/gated** | 11 | 1 | 10 | 1 | `99c8b9c9…a245` |
| value:max/nei0.5/gated | 11 | 1 | 10 | 2 | `79036cb5…80e6` |
| member/nei0.1/gated | 11 | 2 | 9 | 2 | `7d6990cf…02e1` |
| value:max/nei0.1/gated | 11 | 2 | 9 | 3 | `b5bc92b1…a92` |
| value:pooled/nei0.5/gated | 11 | 2 | 9 | 2 | `99443fed…3101` |
| value:pooled/nei0.1/gated | 11 | 4 | 7 | 3 | `9d3320ca…39be` |
| member/nei0/gated | 10 | 4 | 6 | 2 | `badf4254…b9b` |
| value:max/nei0/gated | 10 | 4 | 6 | 3 | `04d36e5d…13a` |
| value:pooled/nei0/gated | 10 | 4 | 6 | 3 | `44f01d13…f48` |

- **Selected: `member/nei0.5/gated`.** It ties `value:max/nei0.5/gated` on b − c and c, and wins on
  changed fields.
- Its only change from the base grounded policy is the gate: member mode and NEI 0.5 are the design
  defaults.
- Dev (dev-informed, no evidence): acc 0.814 against MAJ 0.698, b = 11, c = 1 (p = 0.0063).
  - The one c item, `v5-tqa0731`, is a tied-plurality item where D ≠ MAJ.
  - c_D = 0, F = 3, `harm_bound_holds` true. The gate stage was `verified` on 51 items and
    `plurality` on 35.
- The same configuration was selected under checker 0.1.0 (GATE_SPEC §5), so the choice does not
  depend on the checker change.

**BE (design §5.1 rule over the original six ungated templates).** Largest dev (b − c), then fewest
changed fields, then grid order.

- `member/nei0.1` (b 15, c 9, b − c 6) beats `member/nei0.5`, `value:max/nei0.1` and
  `value:max/nei0.5` (all 5).
- **Selected: `member/nei0.1`**, the same name as under checker 0.1.0. Its template is now
  `084ecdbd…dada0` because `accepted_checkers` changed. The `d135c367…` cited in FRAMING and DEV_GATE
  is the 0.1.0 template.

The confirmatory run evaluates **only** BE-G, BE, B0, EO and the local arm's BE-G-L. The other grid
templates are not run on confirmatory data.

### 5.3 Hosted checker: identity and acceptance

- **Checker.** 0.2.0, `checker_id` `f2a14bd8988371bd231ca6ff137be13e`.
  - `checker_tool_version` `0.2.0+8946ec3b8842.1f3b2cf3404e.fb4c5d09fa695.cli2.1.307`.
  - `claude -p --model claude-sonnet-5-5 --effort low`, all tools off. `flags_sha256` `b4c5d09f…`.
  - `prompt_template_sha256` `41c493e1…5876`. Report:
    `validation/f2a14bd8988371bd231ca6ff137be13e.json` (`7e4d2ba7…`).
- **Fresh-slice results** (`VALIDATION.md`).
  - FEVER: macro-F1 0.899, refutes precision 0.886 (CI lower bound 0.819), supports precision 0.898.
  - Injection: 0/50. Stability: 48/50.
  - SciFact fresh (NEI only): NEI→supports 7/150, NEI→refutes 10/150.
- **Acceptance (made 2026-10-22).** The author accepted checker 0.2.0 `f2a14bd8988371bd231ca6ff137be13e` into `accepted_checkers` for this study (delegated by the author). The grounds:
  - the four spec §2.2 thresholds pass on fresh slices;
  - FEVER supports precision ≥ 0.85.
- **SciFact supports precision cannot be estimated for 0.2.0.** The fresh SciFact slice has no
  supports-gold pairs. The binding "both slices" criterion of FRAMING §3.2 therefore applies only to
  the local checker, which is validated on SciFact-300. Optional pre-freeze step, about $1.4: run
  0.2.0 on SciFact-300 and report it descriptively.
- **CLI pin.** The Claude Code CLI must stay at **2.1.307** for every hosted call (checks, J, RS,
  CB-S, regeneration).
  - A different version changes `checker_id`, and the checks would then be unaccepted. An unaccepted
    check scores at `unchecked_factor` and is never a witness.
  - `judge_id` does not include the CLI version (only `runtime_version` does). The pin is enforced
    operationally and recorded per call.

## 6. Items and the TruthfulQA quota switch

### 6.1 The trigger and the rule

- **Trigger.** Dev evidence availability for TruthfulQA was 4/22 = 0.18, below 0.30 (DEV_GATE §1;
  unchanged under checker 0.2.0). Design §2.2 then moves TruthfulQA's quota to PopQA and FEVER.
  `PREREG_DECISIONS` fixes that k is set here and that items are drawn from `reserve_order.json` in
  order.
- **k.** TruthfulQA's primary quota (300) moves **+150 to PopQA and +150 to FEVER**.
- **Exact draws.** Ids are listed in reserve order. An id-list hash is the sha256 of the ids joined
  by `\n` with a trailing `\n`.
  - PopQA: `reserve.popqa[0:150]`, from `v5-popqa392271` to `v5-popqa3714873`. Ordered-list sha256
    `875f7a97e4aae4d43a1488cebc7e3e62366cb655daf11265172e99ff2f4f73c0`. The PopQA reserve stream is
    round-robin over popularity strata, so the 150 are balanced across strata to within one item.
  - FEVER: `reserve.fever[0:150]`, from `v5-fever43563` to `v5-fever226127`. sha256
    `a076d66464c5e7406483743936312360b350904b4c4bb7288b585526d7de28dc`.
  - Checked: they are disjoint from the 0.1.0 FEVER validation slice, whose 200 supports and refutes
    claims sit at reserve positions ≥ 5,628. They are also disjoint from the 0.2.0 fresh slices,
    which exclude the whole FEVER reserve.
  - The reserve is at `reserve_order.json` sha256 `b5ce52ef…73e3`, unchanged.
- **TruthfulQA no-coverage stratum (FRAMING O7).** It is the **first 100 TruthfulQA items of the
  primary tier in frozen `order`**, orders 0–331 of the current file, 60 Adversarial and 40
  Non-Adversarial. Ordered-list sha256
  `60811e82f13d0041a024c7bae47144a8b241dce79a5f1cb443206d354ce17cc7`.
  - The stratum feeds H3b, the T-columns of H4, and descriptive tables only.
  - It never enters H1 or H2.

### 6.2 The confirmatory collection set (1,100 items)

| source | from the current primary tier | from the reserve | total | set |
|---|---|---|---|---|
| SciFact | 250 (201 SUPPORTED / 49 REFUTED, proportional, as decided) | 0 | 250 | P |
| PopQA | 250 | 150 | 400 | P |
| FEVER | 200 | 150 | 350 | P |
| TruthfulQA | 100 (the stratum) | 0 | 100 | T |
| **total** | 800 | 300 | **1,100** | |

- The sorted id set of all 1,100 has sha256
  `d649d362afe2848921318319adf7a438e0f8cde7cdf983017323e2f24bed19a5`.
- **Not collected (600 items):**
  - the other 200 primary TruthfulQA items;
  - all 400 extension items, which the stopping rule (§9) does not reach.
  - Their sorted ids hash to `ed08e1b0f4fa4341ac13424cf08755c3f4cfd91d6726df2a18326d8954522a05`.

### 6.3 What must be regenerated (not done here)

`collect_v5.py --split conf --n-items I` collects a **prefix** of `items_confirmatory.jsonl`, and the
reserve ids have no item records yet. The item file must therefore be regenerated before the freeze.
This document stops short of editing the benchmark.

1. **`build_benchmark_v5.py`.** Add a pre-declared switch build, `v5-benchmark-1.1.0`, that writes a
   new `items_confirmatory.jsonl` holding exactly the 1,100 items of §6.2.
   - **Records.** Item records for the 300 reserve ids are built by the same mechanical rules as the
     existing ones, from the same local downloads.
   - **Kept records.** The 800 retained records keep every field except `order` and `tier`.
   - **`tier`.** `primary` for the 1,000 P items, `tqa_stratum` for the 100 T items, and a field
     `switch_added: true` on the 300 reserve items.
   - **`order`.** 0–1,099, by the builder's smooth weighted round-robin over the four source streams
     with quotas 250 / 400 / 350 / 100. The streams are:
     - SciFact: primary order;
     - PopQA: primary order, then `reserve.popqa[0:150]`;
     - FEVER: primary order, then `reserve.fever[0:150]`;
     - TruthfulQA: the stratum in primary order.
   - **Prefix balance.** Every prefix stays balanced, as now.
2. **`manifest.json` and `exclusion_proofs.json`.** Regenerate with the new hashes, the switch
   parameters and the id-list hashes of §6.2. Re-assert every `required_zero` intersection, and add:
   - the 300 reserve ids against v4 dev, v4 primary, v4 Stage B requested, the checker validation
     claims (all slices, 0.1.0 and 0.2.0, and any local-checker slice), and v5 dev: all 0;
   - the 1,100 against the not-collected 600: 0.
3. **`reserve_order.json`.** Keep it unchanged. The used ids are identified by position in
   `manifest.json`.
4. **`benchmark/README.md`.** Document the switch build.
5. **Checks after regeneration.**
   - G-AK grades each of the 1,100 gold answers correct (the gold-consistency check).
   - The 800 retained records equal the old ones on every field but `order` and `tier`.
   - The builder is deterministic (byte-identical on rebuild).
6. **Collector.** `collect_v5.py` needs no change. It is run with `--n-items 1100`. The dispatch
   shuffle is one `Random(20261101)` shuffle per item of the new file in frozen order, so it is fixed
   by the new file's hash.
7. **Hashes.** The new `items_confirmatory.jsonl`, `manifest.json`, `exclusion_proofs.json` and
   `build_benchmark_v5.py` go into `FREEZE.json` → `sha256`. Until then, `--split conf` refuses to
   run.

## 7. Metrics

All metrics are computed on P and T separately, then pooled descriptively.

**Accuracy.** On decisive conflicts (primary), and on all eligible items.

**b / c and overturn rates.**

- b, c against MAJ for every method.
- p_w = b/#(MAJ wrong) and q_r = c/#(MAJ right), with Wilson CIs.
- For gated methods, b_D and c_D against D as well.

**Gap-closed fraction.**

- G = (acc − acc_MAJ)/(acc_REF − acc_MAJ), for REF ∈ {J, ORC}, for BE-G, BE, BE-G-L, VV and EO.
- Item-bootstrap 95% CI (10,000 resamples, seed 42). G is undefined when the denominator is ≤ 0.

**Cost, on a uniform basis.**

- Every decider runs on **every disagreement item** (≥ 2 distinct parsed answers), not only on
  decisive items. This includes J, RS, CB-S, J_local and both checkers' checks of all cited
  (proposition, passage) pairs.
- Single-value items need no decision. They are `forced` with no call for every method.
- Per decision we report:
  - hosted USD from the CLI cost reports;
  - model calls;
  - input and output tokens, with cache-creation tokens shown separately;
  - a local-model wall-time and energy proxy (seconds on the M3 Pro).
- Gold-shown checks for the evidence-availability diagnostic are excluded from $/decision and
  reported separately. They are run only on decisive items, with `--gold-restrict` on FEVER and
  SciFact as on dev.

**Latency.**

- Critical path per decision. For BE-G it is the maximum check latency over the item's checks (checks
  run in parallel) plus reducer wall time. For J it is the call wall time.
- Reducer wall time: median and 95th percentile.

**Replay.**

- **BE-G and BE identity.** Each reduction runs twice on every eligible item, and the outputs must be
  byte-identical. The Python mirror must equal the binary on every slot, including the gate trace;
  the run aborts on a mismatch.
- **J regeneration.** 200 disagreement items drawn by `Random("v5-jregen")` from the sorted ids, run
  again with the same pin. We report decision agreement.
- **J_local drift.** The same 200 items at `num_thread` 4 and 8, and after an Ollama restart. We report
  agreement.
- **Counterfactual replay** (leave-one-agent-out).
  - BE-G re-decides each disagreement item 5 times, once per dropped agent, from the sealed labels
    with 0 model calls. We report the time.
  - J's counterfactual cost is 5 new calls per item, priced at its measured per-call cost and
    latency. It is also run on a 50-item seeded subsample (`Random("v5-loao")`, about $3.5), and we
    report how often the decision changes.

**Audit size.**

- For each BE-G overturn: the number of labelled passages that determine it (the witnesses' accepted
  `supports` citations on the winning value), and their total characters.
- For J: input context tokens plus output tokens.

**Majority-following.** For each judge (J, RS, CB-S, J_local), agreement with MAJ on majority-wrong
decisive items.

**Also reported.**

- S4 score separation (δ = 0.05).
- Checker refusals and parse errors.
- The support label distribution.
- Evidence availability per source (diagnostic, never a selector).
- Parse audit.
- Per-agent accuracy.
- Gate stage counts.

## 8. Collection and check protocol

1. **Environment.** As dev (§4.1). The collector verifies model digests, corpus and index hashes, the
   dense manifest and `FREEZE.json` at start-up and aborts on any mismatch.
   - Before the freeze: run `corpus_capture.py --verify-passages` once (PREREG_DECISIONS).
2. **Collection.** `collect_v5.py --split conf --n-items 1100`.
   - It resumes from the next uncollected item after a crash.
   - There are no reruns of completed items.
   - **One non-binding futility look (the only interim analysis).**
     - **When:** after the first 300 collected items in frozen order, which form a balanced prefix (§6.2).
     - **What runs:** those items are captured and checked (step 3 and step 4). The H1a configuration BE-G is reduced against MAJ on the decisive P-source conflicts among them.
     - **What is reported:** only b and c for BE-G vs MAJ. No p-value or CI.
     - **The rule:** if b − c ≤ 0, collection stops for futility, and the study is reported as stopped at the futility look, with the 300-item counts. Otherwise collection continues to all 1,100 items, with no further looks.
     - **Effect on α:** the look can only stop the study and never declares an effect, so α is unchanged and no adjustment is made.
     - **What is not touched:** J, RS, CB-S, J_local and every other analysis run only after collection completes. The interim counts are not used in them.
3. **Captures.** All cited passages are captured once under one fixed epoch, and every check is
   recorded once per de-duplicated pair.
4. **Hosted checks.** `run_checks_v5.py` with `--expect-checker f2a14bd8988371bd231ca6ff137be13e`
   passed explicitly; the script's default is still the 0.1.0 id.
5. **Local checks (if the local arm is confirmatory).** `[[LOCAL-ARM: driver command]]`.
6. **Judges.** J, RS, CB-S and J_local run on all disagreement items. Then the J regeneration, the
   J_local drift runs and the LOAO subsample.
7. **Analysis.** `evaluate_v5.py --split conf` runs **once**, with the frozen binary
   `real-agent-eval/v5/frozen-bin/bran`, then `make_results.py`. The order in `RESULTS.md` is:
   preregistered analyses, then deviations, then exploratory analyses.
8. **Budget (G3 re-ask; about $60).**

   | item | estimate |
   |---|---|
   | hosted checks | ≈ $23 (dev: $0.0207 per item under 0.2.0) |
   | J + RS + CB-S on ≈ 740 disagreement items | ≈ $27 |
   | J regeneration and LOAO subsample | ≈ $7 |
   | gold-shown diagnostic checks | a few dollars |
   | collection | ≈ 7.6 h at ≈ 25 s per item |
   | local checks and J_local | ≈ 6–9 h of local time |

## 9. Sample size and stopping rule (POWER.md, design §6.2)

**The rule, unchanged.**

- I = ⌈N\*(ψ) / y_dev⌉, clamped to [1,000, 1,400].
- N\* is the smallest stable N for 80% power of the exact two-sided McNemar test at Δ = 0.075.
- ψ = max(ψ_dev, 0.25), using b + c only, never b − c.

**Dev values, checker 0.2.0.**

| quantity | value |
|---|---|
| y_dev, all dev | 86/160 = 0.5375 |
| y_dev, non-TruthfulQA | 64/120 = 0.533 |
| ψ_dev, BE vs MAJ (H1b pair) | 0.279 |
| ψ_dev, BE-G vs MAJ (H1a pair) | 0.140 |

We use the larger ψ of the two co-primary pairs, 0.279, which gives N\* = 409:

- on all-dev yield, I_unclamped = 761;
- on non-TruthfulQA yield, I_unclamped = 768.

Under every reading, **I = 1,000** primary (P) items. With checker 0.1.0 the figures were ψ 0.291,
N\* 426 and I 1,000 (DEV_GATE). The switch adds the 100-item T stratum, for **1,100 items collected**.
No extension is allowed.

**Expected power.** About 533 decisive conflicts in P (y 0.533).

- At the planning point, ψ 0.25 and Δ 0.075: power 0.93 at α = 0.05 and 0.88 at Holm's first-step
  α = 0.025. The exact test was computed in a fresh process.
- At dev non-TruthfulQA values for BE-G (ψ 0.172, Δ 0.172): power ≈ 1.

**Caveat.** `v4/power/power.py` caches rejection sets by n only, not by α, so α ≠ 0.05 values are
wrong if computed after α = 0.05 in the same process. The figures here avoid that.

## 10. Multiple comparisons

| family | contents | control |
|---|---|---|
| H1 | H1a, H1b | Holm, family-wise α = 0.05 |
| H2 | H2a → H2b-NI → H2b-S | fixed sequence, own α = 0.05; conditional on §2.3 |
| H3a, H3b | one test each | own one-sided α = 0.025 each |
| H4 | | deterministic check and descriptive |
| H5, §2.4, all other comparisons | | descriptive; Holm-adjusted p-values reported for the §2.4 family against MAJ |

- H2 and H3 are not used to rescue H1. If H1a is not rejected, H3 and H2 are still reported, as they
  fall.

**Sensitivity analyses** (pre-declared, descriptive):

- null judge decisions scored wrong;
- PopQA excluded (as v4 S9);
- MAJ with earliest-arrival ties;
- c and q_r against D instead of MAJ;
- a blinded sample of 100 BE-G overturn witnesses labelled for correctness by a human or by disclosed
  simulated annotators (as v4 Amendment 4), with κ against G-AK.

## 11. Analysis code path (to be frozen by hash)

`evaluate_v5.py` (`cbd3eea0…`) implements the dev pipeline. Its conf mode takes **one** `--be-config`
and has none of the new methods or tests. It must be extended **before the freeze**, then
re-hashed into `FREEZE.json`:

1. Conf mode reduces B0, **BE-G (`member/nei0.5/gated`)**, **BE (`member/nei0.1`)** and EO, plus
   BE-G-L with a second checks file and accepted checker when the local arm is on. It asserts each
   configuration's `policy_template_sha256` against §2.
2. The P / T split, from the item `tier` field.
3. H1a/H1b with Holm; H3a with the Clopper–Pearson bound; H3b with Newcombe at margin −0.03;
   H2a → H2b in fixed sequence.
4. H4 on P and T: c_D, F, the F items, `harm_bound_holds` and F̂.
5. The new methods: CV, CONF, D, CB-S, J_local and VV-L.
6. §7 metrics: gap-closed fraction with bootstrap, uniform cost basis, latency, LOAO, audit size,
   majority-following, J and J_local drift.
7. `--best-model mistral`.
8. The `--selftest` and synthetic tests are extended to cover each new statistic.

Also before the freeze:

- `make_results.py` renders the §2 hypotheses (it still renders the design's H1–H3).
- `tools/judge` gains a CB-S method and template, giving a new judge_id. J's and RS's templates and
  ids stay unchanged.

## 12. Frozen artifacts

### 12.1 Identities (also in `FREEZE.json` → `identities`)

**Hosted.**

- **Checker.** `checker_id` `f2a14bd8988371bd231ca6ff137be13e`, CLI 2.1.307.
- **Judges.** J `4f8c27d90e3c1230dd9b9a91d30530f1` and RS `108a3dee08e1b4286ea879ee070ce4bb`, from
  `judge.py judge-id` at HEAD `abf4f77`. They are unchanged from dev.

**Policy templates.**

| method | template sha256 |
|---|---|
| BE-G | `99c8b9c91c27d4fcf8cb33be2f342eb6dffa175f10802459df52a23ee2a0a245` |
| BE | `084ecdbdcd06193beab228fc9ca21fcf1842f1fffd0326052c5b8908581dada0` |
| EO | `75ee3a54eb249c59a911bd75739f2ad06b6ba924e822e383a7f50f2ed6eb7ac7` |
| B0 | `e08f2ea6ad5c6fdeb36f8eeee2dce1555d6ba9450b25625945128bc06ad25f16` |
| BE-G-L | `[[LOCAL-ARM]]` |

**Bran binary.**

- `af420a5def1a67043706f9d232d198b9244dae55b495c68f63de11e99d65045e`, from `nice cargo build
  --release` at HEAD `abf4f77`. It was a no-op rebuild, and it is the binary of the checker-0.2.0 dev
  run.
- It is copied to `real-agent-eval/v5/frozen-bin/bran`, which is git-ignored.
- Default policy hash `dd8d36e6…`, `reducer_constants_id` `456de373…`.

**Agents and run settings.** BEST = mistral. Model digests are as in `v3/results/run_manifest.json`
(`5aff47cc…`). Seeds: 42 (agents), 20261101 (dispatch), 20261201 (benchmark).

**Local.** `[[LOCAL-ARM: checker_id, J_local judge_id]]`.

### 12.2 Files

`FREEZE.json` → `sha256` (repo-relative keys, the format `collect_v5.py` reads) lists every file that
is final now:

- `CONF_FROZEN` minus the item file;
- the checker, judge, capture and grader code;
- the power code;
- the frozen binary;
- the dev evidence for the selection.

`FREEZE.json` → `pending` lists what must still be added: the regenerated item files, the extended
`evaluate_v5.py` and `make_results.py`, CB-S, the local arm, and this file. `collect_v5.py` reads
only `sha256`. Because `items_confirmatory.jsonl` is not yet listed, `--split conf` aborts with
"requires these files frozen".

## 13. Disclosures

**Dev-informed changes.** Each is disclosed in the paper.

1. **The verified-only gate and NEI factor 0.** Disclosed verbatim (FRAMING §3.4):

   > NEI factor 0 and the verified-only gate were added after inspecting dev c-cases (DEV_GATE §5.2).
   > Dev data therefore provide no evidence for them; only confirmatory data do. The originally
   > selected ungated configuration is tested as H1b.

   The gate is fixed by principle (the H4 theorem). Only its mode and NEI were chosen on dev, by a
   pre-declared rule, over 9 templates.
2. **Checker 0.2.0.**
   - Checker 0.1.0 failed the FEVER refutes-precision threshold on dev-time validation (0.788).
   - The prompt's `refutes` / `not_enough_info` rules were changed ("silence is not refutation") and
     iterated only on the first FEVER slice and the SciFact pilot.
   - It was validated once on fresh slices. The CLI version was added to `checker_id`.
   - All dev labels were re-made with 0.2.0, and both selections were re-run on them. Ungated BE
     dev b/c moved from 17/8 to 15/9; gated from 13/1 to 11/1.
3. **The acceptance criterion.** For a local checker the binding criterion is supports precision
   (FRAMING O6). Under NEI 0.5 with the gate, a false `refutes` can only remove support, while a
   false `supports` can create a witness. The hosted 0.2.0 checker also passes the original
   refutes-precision threshold.
4. **The framing change after seeing dev.**
   - The design's H1 (ungated BE vs MAJ) became H1b.
   - The design's H2 (non-inferiority to the Sonnet judge) was deleted.
   - H1a, H2 (local arm), H3 (no-harm), H4 and the CB-S, CV and CONF baselines were added.
   - These were chosen after the dev results in DEV_GATE §3, FRAMING §0 and GATE_SPEC §5.
5. **The TruthfulQA switch.** It was pre-declared, and it fired on the pre-declared diagnostic. The
   split k = 150 / 150 and the 100-item stratum were fixed after dev. The decisions use availability
   and FRAMING's dev tabulation by source, but not confirmatory data.
6. **Budget and cost basis.** Dev cost measurements set the budget and the "all disagreement items"
   cost basis.
7. **Dev is never pooled** with confirmatory data. FRAMING §0's split counts (non-TQA, gated, $/item)
   are dev-informed.

**Relationship to v4.**

- v4's confirmatory analysis is on hold (v4 Amendment 6): `evaluate_v4.py --split conf` is not run,
  and v4 confirmatory responses are not graded, until this preregistration is frozen.
- No v4 confirmatory result has been seen by anyone working on v5.
- The v5 design computed majority accuracy on v4 **dev** only. That is disclosed as a v4 deviation
  (v4 Amendment 6).
- The v5 items exclude all 600 v4 Stage B items.
- v4 is reported as the closed-book ("uncheckable evidence") control, as it falls.

**Data.** No non-public data are used.

## 14. Pre-written readings (FRAMING §5)

| outcome | headline |
|---|---|
| H1a rejects (b > c), H3a holds, H2 confirmatory and H2b NI or better | Local verify-then-vote matches or beats a same-size judge, with no harm and full replay. |
| H1a and H3a hold, H2b fails | Verification needs a strong labeler. With a hosted checker, gated arbitration overturns [b] wrong majorities with no harm and full replay. Small holistic judges beat small verifiers by [Δ]. |
| Local checker fails validation | H2 "not run as confirmatory; checker unvalidated". Headline H1a + H3 with the hosted checker. Cost is framed as "per-label, reusable, auditable", never "cheaper than J". |
| H1a rejects, H3a fails | "Harm equals checker false supports, as the bound predicts." H4 (c_D ≤ F, F against F̂) leads. |
| H1a null | Report H1b and VV as they fall, through the evidence-availability split. |
| CB-S ≈ J | J and RS measure knowledge of public benchmarks. The regime of interest is a fleet whose decider must not be the frontier model. |

## 15. Pre-freeze checklist

1. `[[LOCAL-ARM]]` slots filled, or H2 dropped to exploratory (§2.3). **Done: H2 dropped to exploratory (local checker failed).**
2. Item regeneration (§6.3) done and hashed. **Done: `v5-benchmark-1.1.0`, `items_confirmatory.jsonl` `38987c42…`.**
3. `evaluate_v5.py`, `make_results.py` and the CB-S judge extended (§11), tested and hashed. The CB-S
   judge_id is recorded. **Done: CB-S judge_id `1de78d843c35f57cfa9d2ebfd708f681`.**
4. Local-arm code (`local_check.py`, `local_pin.json`, `local_judge.py` and its pin, the driver)
   committed and hashed. **Done (commit 03b7ed4); hashes in FREEZE.json.**
5. `corpus_capture.py --verify-passages` run once; result recorded. **Done 2026-10-22: fever17 and scifact passages re-hash to the manifest.**
6. The author accepts checker 0.2.0 into `accepted_checkers` (§5.3), and re-approves G3 at about $60. **Done 2026-10-22: G3 approved at about $50–60. Checker acceptance, the futility look (§8) and freeze approval were delegated by the author.**
7. `FREEZE.json`: `pending` emptied, `status` set to frozen, and the sha256 of this file added; then
   commit.

### 15.1 Confirmations at freeze (delegated by the author)

- An H2 step counts as rejected only if p ≤ 0.05 and b > c. H2 is exploratory regardless (§2.3).
- The reading "CB-S ≈ J" means |accuracy difference| ≤ 0.03 on P.
- The confirmatory run aborts if any replay is not byte-identical.
- F̂ counts every accepted, ok-status check on an incorrect value's citations.
- **Known input gaps, reported as deviations:**
  - hosted check records carry no token counts, so check tokens are reported as n/a;
  - J and RS rows exported by `run_checks_v5 judge-rows` fold cache tokens into input tokens and carry no judge_id, so the judge_id is asserted only for CB-S.

## 16. Amendments

None yet.
