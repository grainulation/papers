# v5 framing review, before the preregistration freeze

Status: advice only, 2026-10-22. This file was written from `v3/DESIGN.md`, `v3/PREREG_DECISIONS.md`,
`real-agent-eval/v5/DEV_GATE.md`, the v5 **dev** outputs (`results/dev/eval/*.json|csv|jsonl`,
`results/dev/judge.jsonl`, `check_calls.jsonl`, `checks*.jsonl`), `paper/sections/*.tex`,
an earlier review of the paper (not included) and `v3/PUBLIC_FIELD_REPRO.md`. Nothing under `real-agent-eval/v4/results/conf/`
or the author's private notes was read. No model was called. The split counts in §0 (non-TQA, gated, $/item) were
re-tabulated from existing dev outputs, so they are **dev-informed** and must be disclosed if used.

## 0. Dev facts the framing has to survive (86 decisive conflicts)

| method | acc | b / c vs MAJ | note |
|---|---|---|---|
| MAJ | 0.698 | | |
| BEST (mistral) | 0.663 | 14 / 17 | |
| B0, Bran without evidence | 0.558 | 7 / 19 | unverified citation weighting **hurts**; q_r = 0.32 |
| BE (member/nei0.1) | 0.802 | 17 / 8 | p = 0.108; p_w 0.65, q_r 0.13 |
| EO (evidence-only weights) | 0.791 | 16 / 8 | BE vs EO: 2 / 1, so the other four features add ~nothing |
| VV, verified vote | 0.826 | 11 / 0 | p = 0.001 (2·0.5¹¹); falls back to MAJ on 33 / 86 |
| J, Sonnet 5.5 judge | 0.965 | 23 / 0 | J never overturned a right majority |
| RS, Sonnet reader | 0.977 | 24 / 0 | reads the union of the agents' retrieved passages |

- **What drives b and c.** 11 of BE's 17 b-winners carry ≥ 1 `supports` label. The other 6 won on NEI-citation
  volume, which is the same mechanism as all 8 c-cases (no c-winner carries a `supports` label). A "restrict to
  verified candidates, else MAJ" rule therefore reproduces VV on dev: b = 11, c = 0.
- **By source.** TruthfulQA (22 items) is where BE hurts: 2 / 6, BE 0.50 against MAJ 0.68. Its gold is supported
  on 1 of 273 shown passages. The pre-declared §2.2 switch removes TQA from the confirmatory primary.
  - On the other 64 items: MAJ 0.703, BE 0.906 (15 / 2, p = 0.002), VV 0.875 (11 / 0), J 0.969, RS 0.984.
- **Gap closed** to J, (acc − MAJ)/(J − MAJ):
  - all dev: BE 39%, VV 48%;
  - without TQA: BE 76%, VV 65%.
- **Cost per decisive item (dev, measured).**

  | step | USD | tokens | wall |
  |---|---|---|---|
  | BE's Sonnet checks (4.49 per item × $0.0047) | **$0.0217** | | 3.1 s median per check |
  | J | $0.0139 | 3.7k in, 98 out | 3.1 s |
  | RS | $0.0170 | 4.7k in | |
  | reducer | $0 | | 5 ms |

  **With a Sonnet checker, BE costs 1.56× the Sonnet judge.** About 750 cache-creation tokens per CLI call
  dominate the check cost.
- **Replay and separation.** Replay held on 160 / 160 items, and the mirror matched on 1,280 / 1,280 slots. S4
  separation held on 18 / 86 grounded conflicts, against 0 / 29 on free text.
- **Checker on FEVER.** Supports precision is 0.862 and NEI→supports errors are 13 / 100. Refutes precision is
  0.788, which fails the 0.80 threshold.

## 1. Is the proposed framing sound?

The framing is "Bran is the cheap, replayable decider when you don't want a bigger model deciding; a same-class
local judge is the fair baseline; the Sonnet judge is the upper reference".

**Verdict: not sound as stated. It becomes sound only with a local-checker arm.** Three of its four clauses fail
on dev:

1. **"Cheap" is false.** BE costs $0.0217 per item against J's $0.0139. Only the reducer is ms-level; the checks
   dominate the cost.
2. **"No bigger model deciding" is false.** A Sonnet `supports` label is the decisive input in every justified
   overturn.
3. **"Same-class judge as the fair baseline" is a strawman.** Comparing a BE that gets Sonnet labels with a 7B
   judge that gets none is unfair, and reviewers will say so in the first paragraph. Fair comparisons hold the
   model tier fixed: Sonnet checker vs Sonnet J (exists, J wins by 16 points), and local checker vs local J
   (missing).

The fourth clause, "Sonnet J as the upper reference", is right. Add a closed-book Sonnet so the reference is
interpretable.

**Strongest objections:**

| # | objection (reviewer voice) | severity | answer type | answer |
|---|---|---|---|---|
| O1 | "The checker is Sonnet, so BE is a Sonnet judge in disguise: more expensive (1.56×) and 16 points worse." | **fatal for the cost and accuracy framing** | extra baseline + reframe | Add the local-checker arm (§3.2). Reframe the contribution as decomposition: the model's role shrinks to an atomic, validated, sealed label that never sees headcount, so a 7B specialist can do it and a human can audit it. Never claim BE is cheaper than J with a hosted checker. |
| O2 | "Sonnet gets 97.7% from passages alone. Why have agents, or Bran?" | serious | extra baseline + framing | (i) Add closed-book Sonnet (CB-S). If CB-S ≈ 0.95, J and RS measure memorisation of public benchmarks, not adjudication (design §7.3). (ii) RS reads the passages the *agents' queries* retrieved, so it is not "agent-free". (iii) Scope: fleets exist because a frontier model is too costly, private or unavailable for every call. Bran targets the decider for that fleet. Concede that on public benchmarks a frontier model simply knows the answer. |
| O3 | "BE ≈ VV ≈ EO. The 5-feature scorer, Schulze and the Lean results are irrelevant to accuracy." | serious for one-paper coherence | framing + new theorem | Make VV-style gating a Bran policy. State the finding honestly: once candidates are restricted to verified ones, the scoring rule hardly matters. B0's −14 points is a citable caution against unverified evidence weighting. Add a gate-soundness theorem (§3.1, H4) so the Lean half speaks to the grounded half. |
| O4 | "Replay is trivial: cache J's output." | moderate | analysis | Caching reproduces *a* decision; it cannot re-decide. Measure **counterfactual replay** (leave-one-agent-out, policy change): BE takes 0 model calls and ms, J needs 5 new calls and drifts. Measure **audit size**: BE's decision witness is 1–3 labelled passages, J's is a 3.7k-token context plus a free-text rationale. Also measure J regeneration drift (200 items) and local-judge drift across thread counts and builds. |
| O5 | "The grid was extended after seeing dev c-cases (forking paths)." | moderate | disclosure + design | Fix the gate by principle (the theorem), not by dev score. Keep the originally selected ungated BE as a co-tested secondary. Disclose verbatim (§3.4). Confirmatory items are fresh. |
| O6 | "The checker failed its own FEVER acceptance threshold." | moderate | design fix | Under NEI factor 0 with gating, refutes and NEI both score 0, so refutes precision no longer affects any decision. Only false supports can cause harm. Make supports precision the binding criterion (FEVER 0.862, SciFact 0.923) and disclose the change. |
| O7 | "The small-agent setting is artificial, and dropping TQA cherry-picks." | moderate | framing + one stratum | The regime (majority wrong in 30% of conflicts, with a citing correct minority) is measured, not assumed. Keep a 100-item TQA stratum where corpus coverage is absent, as a pre-declared safety test: the gate should do no harm there, while ungated BE did harm on dev. |
| O8 | "Verifier-weighted voting is known (ORM-weighted voting, ALCE citation NLI)." | moderate | related work | Concede it. Bran's delta is citation-level checks on a sealed corpus, a harm bound, cross-platform replay, and a benchmark for deciders. Cite Lightman 2023, Generative Verifiers (ICLR'25), ALCE (EMNLP'23) and MiniCheck (EMNLP'24). |
| O9 | "There is no debate baseline." | minor | optional baseline | The debate-vs-vote literature (Choi 2025, Zhang 2025, already cited) predicts debate ≈ vote. One debate round costs about 9 h of local time. It is optional (§3.2). |

## 2. Alternative framings

**(a) Cost, audit and replay Pareto frontier.**

- **Claim.** "Evidence-gated deterministic arbitration is the most accurate fully replayable decider, and is on
  the accuracy–$ frontier at matched model tier."
- **Needs.** The local checker and judges, a uniform cost basis, and a replay axis.
- **Likely result.** With a Sonnet checker, BE is *dominated* by J on both accuracy and $. Only a local BE can sit
  on the frontier.
- **Risk.** Medium. A frontier where your method loses two of three axes is a weak headline.
- **Citation potential.** Medium. Cost-controlled evaluation is now expected (Kapoor et al. 2024, "AI Agents
  That Matter"), so this is a required figure, not the thesis.

**(b) "Verification beats deliberation".**

- **Claim.** "Per-passage verification plus deterministic aggregation recovers most of a strong judge's gain at
  a fraction of the tokens, with replay."
- **Likely result.** The gain part holds: 48% of the gap overall and 65–76% without TQA. The token part is
  **false** with a hosted checker (1.56× the $). "Beats" is contradicted by J's 0.965 against the dev values.
- **Risk.** High as worded. Usable only as "verification by a *same-tier* model beats *same-tier* judging", which
  is H2b below and still unknown.
- **Citation potential.** High if true, because it hits a hot topic.

**(c) "Evidence-gated arbitration overturns wrong majorities without overturning right ones".**

- **Claim.** H1 vs MAJ, plus a no-harm bound, with J as reference.
- **Needs.** Nothing new beyond the gate.
- **Likely result.** Near-certain. The non-TQA dev projection is b ≈ 90–130 and c ≈ 0–20 over about 540 decisive
  conflicts.
- **Risk.** Low statistically, high for "so what, Sonnet does it better".
- **Citation potential.** Moderate alone; high when paired with (d) and (e).

**(d) Weak, local checker.**

- **Claim.** "A local 7B verifier plus a frozen rule turns a 2–8B fleet into a fully local, replayable system
  that beats majority and [matches/beats] a same-size judge."
- **Needs.** Validation of the local checker on the existing SciFact-300 and FEVER-300 slices, local checks
  (≈ 3k), and a local judge.
- **Likely result.** Unknown. MiniCheck-class models reach GPT-4-level grounding accuracy (Tang et al. 2024), and
  small judges tend to follow the majority (to be measured).
- **Risk.** Medium.
- **Citation potential.** High. It removes O1, makes "cheap" true, and matches the PoLL/MiniCheck narrative
  ("smaller models suffice when the task is narrowed").

**(e) Benchmark for deciders ("OVERTURN").**

- **Claim.** A frozen set of multi-agent disagreements with sealed retrieval, citations, labels and gold. Any
  decider is scored offline on accuracy, harm (q_r), $ and replay.
- **Needs.** Packaging only: Croissant metadata and hosting on HF, as NeurIPS E&D requires.
- **Risk.** Saturation, since Sonnet is near 97%. Mitigate with a "local / replayable" track, where MAJ is 0.70
  and there is headroom, and a no-coverage split.
- **Citation potential.** High if adopted. Benchmarks for the *aggregation step* are rare. The closest work
  (RAMDocs/MADAM-RAG, ClashEval, WikiContradict) tests one model reading conflicting documents, not deciders over
  agents.

**(f) Safety-first arbitration with a proof.**

- **Claim.** "Restricting overturns to checker-verified candidates is provably never worse than majority except
  through checker false supports. Empirically, c ≈ 0."
- **Needs.** A Lean lemma (about 30 lines) and the F count (§3.3).
- **Likely result.** Dev c = 0 of 60 right majorities.
- **Risk.** Low.
- **Citation potential.** Moderate–high in the agent-safety and audit communities. It also ties the Lean half to
  the data.

**Recommendation: (c) + (f) as the headline, (d) as the key secondary that answers O1, (a) as the mandatory
figure, and (e) as the release.** In one sentence: *verify, then vote*. A checker labels each cited passage once,
the labels are sealed, and a frozen rule may overturn the majority only through a verified candidate. This
provably bounds harm by checker false supports, replays bit for bit, and runs fully locally with a 7B verifier.

Why this combination:

- The primary result is near-certain, which avoids honest-null slop.
- The risky comparison (local BE vs local judge) is secondary, and either outcome is a finding.
- J and RS stay as references and are never parity targets.
- Keep the v4 closed-book study as the "uncheckable evidence" control, reported as it falls.
- Keep `PUBLIC_FIELD_REPRO.md` **out** of this paper. Its feasibility sample is at chance on truth-related reasons
  (49%, CI 37–61%), and it answers a different question.

## 3. Changes to the v5 preregistration before the freeze

### 3.1 Hypotheses (decisive conflicts, primary sources SciFact / PopQA / FEVER after the §2.2 switch)

**H1a (primary).** BE-G, the evidence-gated reducer with the Sonnet checker, beats MAJ.

- BE-G is defined in §3.4: candidates are restricted to those with ≥ 1 accepted `supports` label, the frozen
  Bran score selects among them, and the rule falls back to MAJ if none is verified.
- Test: exact two-sided McNemar.

**H1b (co-primary).** BE, the dev-selected ungated `member/nei0.1` (template `d135c367…`), beats MAJ. H1a and H1b
use Holm at α = 0.05; both are expected to reject.

**H2 (key secondary family, fixed sequence, α = 0.05).**

1. **H2a.** BE-G-L (BE-G with the local checker) beats MAJ.
2. **H2b.** BE-G-L is non-inferior to J-7B, margin −0.05 with the one-sided Newcombe bound. If it holds,
   superiority is tested.

**H3 (no-harm).**

- Primary sources: q_r(BE-G) has a one-sided 97.5% Clopper–Pearson upper bound below 0.05 on majority-right
  decisive items.
- TQA no-coverage stratum: BE-G is non-inferior to MAJ, margin −0.03.
- Ungated BE is reported on the same two tests.

**H4 (gate soundness, proved plus checked).**

- Lean lemma: if no incorrect candidate carries an accepted `supports` label, BE-G is correct whenever MAJ is or
  any correct candidate is verified. Hence c ≤ F, where F is the number of items on which an incorrect candidate
  carries a supports label.
- Report c, F, and F predicted from the validation false-supports rate, so you can show that "validation metrics
  predict deployment harm".

**H5 (descriptive).**

- Gap-closed fraction against J-Sonnet and against ORC.
- The cost, latency and replay table, and the Pareto figure.
- BE-G vs VV and BE vs EO, expected to be equivalent and reported as such.

**Delete the design's H2 (BE non-inferior to Sonnet J).** It is unwinnable (dev −0.163, CI −0.25 to −0.09).
Pre-declare instead that J is expected to exceed BE, so the gap cannot later be spun.

### 3.2 Baselines and local models

From the repo (`collect_v5.py` MODELS, `real-agent-eval/v3/results/run_manifest.json`), the only local LLMs are
the five agents:

- llama3.2:3b, 3.2B, Q4_K_M;
- mistral:latest, 7.2B;
- gemma2:2b, 2.6B;
- phi3:mini, 3.8B;
- qwen2.5:3b, 3.1B;
- plus nomic-embed-text.

They total about the 12 GB the design measured. The names qwen2.5:7b, llama3.1:8b and gemma2:9b appear only as
fixtures in `tools/judge/tests/test_judge.py`, which is no evidence that they are installed.

| id | model | why | cost |
|---|---|---|---|
| **J-7B** (H2b) | `qwen2.5:7b` instruct, Q4_K_M | Strongest credible same-tier, non-participant judge from the agents' vintage; reliable JSON; 32k context | ≈ 4.7 GB download; ≈ 20–30 s per item → ≈ 4–5 h on about 670 disagreement items |
| J-M | `mistral` (participant, the best agent) | The practitioner move "promote the best agent to judge". Zero download. Report a self-preference diagnostic. | ≈ 3–4 h |
| J-14B (optional) | `qwen2.5:14b` | Same family, so it gives a clean judge-size curve: 7B → 14B → Sonnet | ≈ 9 GB, gated on disk; ≈ 8–10 h |
| **BE-G-L, VV-L** (H2) | `bespoke-minicheck:7b` (Ollama) as checker | Purpose-built (document, sentence) verifier. Its yes/no output is lossless under NEI 0. CC BY-NC 4.0, so check the label-release licence. | ≈ 4–5 GB; ≈ 3k checks at 2–4 s ≈ 2–3 h |
| fallback checker | `mistral` with the current checker prompt | Zero download. Used only if MiniCheck fails validation, in this pre-declared order | |
| **CB-S** | Sonnet, question and options only | Quantifies memorisation (O2) | ≈ $0.006 per item |
| CV | cite-vote: plurality among answers with any citation, unverified | Isolates *verification* from *citing*. Free. | |
| conf-vote | plurality weighted by stated confidence | The standard cheap baseline. Free. | |
| Haiku J (optional) | `claude-haiku-4-5` | A hosted mid-tier point on the frontier | ≈ $3 |
| Debate-1 (optional) | one revision round by the five agents over each other's answers and cited passages, then MAJ | Answers O9 | ≈ 9 h local |

Rules for every judge and checker:

- Every local judge uses `prompt_J.txt` unchanged, Ollama structured output, temperature 0, a fixed seed and
  **num_ctx 8192**. J inputs average 3.7k tokens, so the agents' 4096 would truncate.
- Validate each local checker on SciFact-300 and FEVER-300 before the freeze. Binding criteria: supports
  precision ≥ 0.85 on both slices, macro-F1 ≥ 0.70, stability ≥ 0.95. This uses no dev outcomes.

### 3.3 Metrics to add

- **Uniform cost basis.** Every decider runs on every item with ≥ 2 distinct parsed answers (≈ 67%), not only on
  gold-defined decisive items as J and RS did on dev. Report:
  - $ per decision and model calls per decision;
  - input and output tokens;
  - critical-path latency, with checks run in parallel;
  - local wall time and energy proxy (s on the M3 Pro).
- **Gap-closed fraction.** G = (acc − MAJ)/(REF − MAJ) for REF ∈ {J-Sonnet, ORC}, with an item-bootstrap CI.
- **Harm.** q_r with a Wilson CI, made a first-class column. Also F and the bound check from H4.
- **Replay.**
  - BE identity on all items;
  - J-Sonnet regeneration agreement (200 items);
  - J-7B agreement across `num_thread` {4, 8} and an Ollama restart;
  - counterfactual replay: 5 leave-one-agent-out re-decisions per item, counting model calls and time.
- **Audit size.** The decision witness: the number of labelled passages that determine a BE-G overturn, against
  J's context tokens.
- **Majority-following.** Each judge's agreement with MAJ on majority-wrong items. This is where small judges are
  expected to fail.

### 3.4 Decision-rule grid additions

The grid becomes {member, value:max, value:pooled} × NEI {0.5, 0.1, **0**} × gate {off, **verified-only**}, so
18 templates, all hashed.

- **verified-only.** Candidates are restricted to contributions with ≥ 1 accepted `supports` label, the policy
  score selects among them, and MAJ is the fallback when none is verified. VV is the same restriction with
  headcount.
- **Implementation.** Implement the gate in the Rust reducer, so a Bran certificate covers it and the binary hash
  is re-frozen. A Python composition is weaker for the systems claim.
- **Selection.**
  - The gate is fixed by principle, through the H4 theorem.
  - Within gated templates, the pre-declared rule picks the largest dev (b − c) on all 86 dev decisive items,
    breaking ties by smaller c, then fewer changed fields, then grid order.
  - Selecting on all dev rather than on non-TQA dev avoids a choice that depends on the switch.
- **Disclosure text (verbatim):**
  > NEI factor 0 and the verified-only gate were added after inspecting dev c-cases (DEV_GATE §5.2). Dev data
  > therefore provide no evidence for them; only confirmatory data do. The originally selected ungated
  > configuration is tested as H1b.
- **Also disclose:** the checker acceptance criterion moved from refutes precision to supports precision (O6).

### 3.5 Other fixes

- **Fix the switch split k** (for example PopQA +150, FEVER +150 from `reserve_order.json`) and the 100-item TQA
  stratum.
- **SciFact REFUTED allocation.** Keep it proportional (49 / 250), as decided.
- **Run RS and CB-S on all disagreement items.** This also fixes DEV_GATE §5.6.
- **Budget.**

  | item | estimate |
  |---|---|
  | Sonnet checks | ≈ $30 |
  | J + RS + CB-S on ≈ 670 items | ≈ $25 |
  | J regeneration | $3 |
  | Haiku (optional) | $3 |
  | **total** | **≈ $60** (re-ask G3) |
  | local machine time (beyond the 7 h of collection) | +6–9 h, or +17 h with the optional J-14B and debate |
  | disk for the local models | ≈ 10 GB without J-14B (new G1b) |

## 4. Title, abstract and contributions under the recommended framing

**Title (preferred).** *Verify, Then Vote: Sealed, Replayable Arbitration for Disagreeing LLM Agents*

**Alternate, if H2b is positive.** *Verify, Then Vote: Small Verifiers Overturn Wrong Majorities Without a Judge*

**Abstract skeleton (≈ 120 words):**

> When LLM agents disagree, a vote cannot overturn a shared error, and a model judge can be neither replayed nor
> audited. We study *verify, then vote*: a checker labels each cited passage once, the labels are sealed, and a
> frozen rule may overturn the majority only through a verified answer. Bran implements this as a pure function
> of a hashed input that replays bit for bit across builds in [x] ms, and we prove that its harm is bounded by
> checker false supports. On OVERTURN, a preregistered benchmark of [N] disagreements among five 2–8B retrieval
> agents where the majority is wrong in [m]% of cases, it overturned [b] wrong majorities and [c] right ones
> ([a] vs [a₀], p = [·]). That closes [g]% of the gap to a frontier judge. With a local 7B verifier it
> [beat / matched / trailed] a same-size judge ([·] vs [·]) at [$·] per decision.

**Contributions (replace the five findings):**

1. **Verify-then-vote with a harm bound.** A gated arbitration rule and a Lean proof that c ≤ F. It is measured:
   [c] against [F] against the predicted [F̂].
2. **The sealed boundary.** This is the existing systems half: replay across 4 builds and 2 ISAs, 36 / 36 tamper
   cases, ms reduction. It adds counterfactual replay at 0 model calls.
3. **The preregistered grounded study.** H1a/b, no-harm, matched-tier judge contrast, and the cost/replay
   frontier. Closed-book (v4) against grounded (v5) shows that checkable evidence is the precondition.
4. **Cautionary findings for any evidence-weighted aggregator.**
   - Unverified citation weighting is worse than voting (B0 −14 points, q_r 0.32).
   - Feature-rich scoring adds nothing over verified evidence (EO ≈ BE ≈ VV).
   - Recency leaks through the tie-break.
   - Polarity-blind grading inflates gains.
5. **OVERTURN and `pip install bran`.**
   - The release contains frozen conflicts, retrieval records, sealed labels from two checkers, gold and a scorer.
   - The leaderboard has a local and a hosted track, with harm and $ reported alongside accuracy.
   - Licensing: FEVER lines force CC BY-SA. MiniCheck labels are NC, so check before release.

## 5. Risks to the headline and pre-declared fallbacks

The headline sentence is written for each outcome now, so every cell is publishable.

| outcome | probability given dev | headline used |
|---|---|---|
| H1a rejects, H3 holds, H2b NI or better | plausible | the full title above: local verify-then-vote ≥ same-size judge, no harm, replayable |
| H1a and H3 hold, H2b fails (J-7B > BE-G-L) | plausible | "Verification needs a strong labeler: with a hosted checker, gated arbitration overturns [b] wrong majorities with no harm and full replay. Small holistic judges beat small verifiers by [Δ]." Decomposition is reported as an audit trade-off, priced in points. |
| local checker fails validation (both candidates) | possible | Drop H2 as "not run; checker unvalidated" (pre-declared). The headline is (c) + (f) with the Sonnet checker. Cost is framed as "per-label, reusable, auditable", never "cheaper than J". |
| H1a rejects, but c > 5% bound (H3 fails) | unlikely (dev c = 0 / 60) | "Harm equals checker false supports, exactly as the bound predicts." H4 becomes the headline: validation precision predicts deployment harm. |
| H1a null | very unlikely | Use H1b or VV. Report through the evidence-availability split: overturns are capped by how often the corpus holds the minority's support. |
| CB-S ≈ 0.95+ | likely | Strengthens the scope statement. J and RS are knowledge references; the regime that matters is a fleet whose decider must not be the frontier model. |
| reviewer: "artificial small fleets" | certain | Scope paragraph plus the benchmark (any fleet can be plugged in). Stronger fleets are future work; do not over-generalise. |
| reviewer: "two papers in one" | likely at NeurIPS/ICLR | One thesis, *the decision boundary*: what goes through it (verified labels), which rule is safe (H4), and that it is exact and free (systems). Submit to MLSys or NeurIPS main. Spin OVERTURN to E&D only if the main paper fails. |

**Venue expectations (from the sources below).**

- NeurIPS E&D needs Croissant metadata and a preferred host.
- Cost-controlled agent evaluation and Pareto reporting are now standard asks.
- ACL reviewers will ask for human validation of the checker and grader. Keep the planned human sample and add
  about 100 overturn witnesses.
- Self-preference (Panickssery et al. 2024) must be diagnosed for J-M.

## 6. Sources (related work found or confirmed for this note)

- [MiniCheck, EMNLP 2024](https://aclanthology.org/2024.emnlp-main.499) ·
  [Bespoke-MiniCheck-7B model card](https://huggingface.co/bespokelabs/Bespoke-MiniCheck-7B/blob/main/README.md?code=true) ·
  [Ollama tag](https://ollama.com/library/bespoke-minicheck:7b-q5_K_M)
- [Replacing Judges with Juries (PoLL)](https://arxiv.org/pdf/2404.18796)
- [RAG with Conflicting Evidence (MADAM-RAG / RAMDocs)](https://arxiv.org/pdf/2504.13079) ·
  [ClashEval, NeurIPS 2024 D&B](https://arxiv.org/html/2404.10198v2)
- [Large Language Monkeys, the selection gap](https://arxiv.org/abs/2407.21787v3) ·
  [Generative Verifiers, ICLR 2025](https://proceedings.iclr.cc/paper_files/paper/2025/file/214308a2d5e3f83ef9ad2739e1cbc46d-Paper-Conference.pdf)
- [ALCE](https://arxiv.org/pdf/2305.14627)
- [NeurIPS hosting / Croissant](https://neurips.cc/Conferences/2025/DataHostingGuidelines) ·
  [NeurIPS 2026 E&D hosting](https://neurips.cc/Conferences/2026/EvaluationsDatasetsHosting)
- [Judge-stability audit study](https://arxiv.org/html/2601.11783v1)
- Cited from memory, verify before citing:
  - Kapoor et al. 2024, "AI Agents That Matter";
  - Panickssery et al. 2024, self-preference;
  - Lightman et al. 2023, "Let's Verify Step by Step";
  - Longpre et al. 2021, entity-based knowledge conflicts.

## Executive summary

1. The proposed framing fails on dev. With a Sonnet checker, BE costs 1.56× the Sonnet judge ($0.0217 vs $0.0139 per item) and is 16 points worse.
2. A larger model *does* decide, through its labels. A 7B judge against a Sonnet-labelled BE would be a strawman. Match the model tier instead.
3. The dev signal that survives is gating. Restricted to verified candidates, the rule gives b = 11, c = 0 (p = 0.001), and every BE c-case came from unverified NEI citation volume.
4. Headline: *verify, then vote*. Overturn the majority only through a checker-verified answer, and prove that harm ≤ false-support events (a Lean lemma that links the two halves).
5. Primary H1a is BE-G vs MAJ, with the original ungated BE as Holm co-primary H1b. Both are near-certain to reject on post-switch sources (dev without TQA: BE 0.906, VV 0.875, MAJ 0.703).
6. Drop non-inferiority to Sonnet J (unwinnable). Keep J, RS and a new closed-book Sonnet as references, and report the gap closed (dev: 39–48% overall, 65–76% without TQA).
7. Key secondary: BE-G with a local `bespoke-minicheck:7b` checker vs MAJ, then vs a `qwen2.5:7b` judge (non-participant, same tier). Add J-mistral, plus an optional `qwen2.5:14b` for a size curve.
8. Grid: add NEI 0 and the verified-only gate, implemented in Rust, with dev-informed disclosure. Bind checker acceptance to supports precision; this also defuses the FEVER refutes miss.
9. Add: a uniform cost basis on all disagreement items, harm q_r, counterfactual-replay cost, audit size, majority-following, a 100-item TQA no-harm stratum, and num_ctx 8192 for local judges. Budget ≈ $60 and +6–9 h local.
10. Every outcome cell has a pre-written headline. Ship OVERTURN (Croissant, CC BY-SA) and `bran` on pip. Keep the Wikidata field reproduction out of this paper.
