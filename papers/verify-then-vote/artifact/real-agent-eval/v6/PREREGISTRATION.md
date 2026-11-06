# Eval v6 preregistration: verify, then vote, with a second agent pool

> **STATUS: FROZEN (2026-10-24).** Approved by the author on 2026-10-24 ("go"), including the
> budget (§8.8, cap $60) and the removal of the local-checker arm (§2.5). The pool passed
> qualification after one pre-declared replacement (§4.3). Every file listed in
> `real-agent-eval/v6/FREEZE.json` is hashed there, including this one.
>
> Changes after the freeze are amendments: dated, appended in §16, and never applied retroactively
> to data already seen.
>
> **Revision 2 (2026-10-24).** This revision adds the "verified default first" (VDF)
> methods from the post-hoc `v5/selector_study/`. VV/VDF is now the primary method for H1a and H3a
> (family F1). BE-G, the v5 primary, is kept as a replication family (F2). The pooled H3a stays
> secondary, for BE-G only. See §2, §5.2, §9.4 and §13 item 2.
>
> **Revision 3 (2026-10-24).** This revision adds:
>
> - a secondary grader with frozen Wikidata aliases (§3.1);
> - the pre-freeze tuning screens (§13 item 9).

Inputs read for this preregistration: `real-agent-eval/v5/PREREGISTRATION.md` (including §15.1 and §16),
`v5/README.md`, `v5/FREEZE.json`, `v5/collect_v5.py`, `v5/post_collect_v5.py`, `v5/evaluate_v5.py`,
`v5/power/POWER.md`, `v5/results/conf/RUN_NOTES.md`, `v5/results/conf/RESULTS.md`,
`v5/benchmark/README.md`, and the v5 confirmatory raw records (for wall time and for the
check-cache overlap estimate only). Revision 2 also read `v5/selector_study/README.md`,
`results.json` and `selector_study.py`. Nothing under `v3/internal/` was read.

## 1. Background: why a second pool

Eval v5 tested "verify, then vote" with one pool of five small agents (llama3.2:3b, mistral,
gemma2:2b, phi3:mini, qwen2.5:3b), one seed, one machine. On its primary set P (526 decisive
conflicts) it found:

- **H1a held.** BE-G vs MAJ: b = 91, c = 12, exact McNemar p = 3.5e-16.
- **H1b held.** BE vs MAJ: b = 99, c = 23, p = 2.0e-12.
- **H3a failed narrowly.** BE-G overturned 12 of n_R = 376 right majorities (q̂_r = 0.032). The
  one-sided 97.5% Clopper–Pearson upper bound was 0.0551 against a 0.05 ceiling. The largest c that
  would have passed at n_R = 376 was 10.
- **H3b held.** On the TruthfulQA stratum T, BE-G vs MAJ: b = 9, c = 1, Newcombe lower bound 0.030 > −0.03.

(Note for the author: the task brief quotes 12/373. The v5 `RESULTS.md` H3 table reports
n_R = 376, which is what this document uses. 12/373 and 12/376 both round to 0.032.)

Two weaknesses follow:

- **(a) Generality.** All v5 evidence comes from one pool. A rule that arbitrates *between* agents
  could depend on how those particular agents err.
- **(b) H3a.** The no-harm test missed by a small margin. Its result is not "harm shown". It is
  "a harm rate below 5% not shown".

Eval v6 repeats the v5 confirmatory study with a **different pool of five small open-weight agents**
and **everything else frozen identical to v5**. It gives a second, independent confirmatory test of
H1a/H1b and H3a/H3b on new conflicts. It also pre-declares, as secondary, a pooled v5 + v6 test of
H3a.

**What v6 changes, and what it does not.**

- **One new method family, pre-declared here and confirmatory for the first time in v6: "verified
  default first" (VDF).** It comes from a post-hoc study of v5's confirmatory data
  (`v5/selector_study/`). That study found that keeping the default whenever the default is itself
  verified removes most of the gate's harms at almost no cost. It also found that VDF is still an
  instance of the gate theorem. **VDF was designed after seeing v5's confirmatory data, including
  its harm cases. That is why it is tested only here, on a new pool, and never on v5's data** (§13).
  - VV/VDF becomes the v6 primary method for H1a and H3a (§2.1).
  - BE-G, the v5 primary, is kept as a separate replication family (§2.2).
- **The H3a ceiling stays at 0.05** for every method, and the H3a and H1 tests keep v5's form. The
  checker, policy templates, frozen binary, evaluator, judges, grader and items are unchanged.
- **Code.** VDF is a deterministic rule applied after the frozen reducer and the frozen VV. It needs
  no new policy template and no Rust change (§5.2). It is computed in a v6 evaluator wrapper (§11).
- **Pool.** The other manipulated factor is the agent pool. With it come the qualification run that
  must precede any new pool (§4.3) and BEST, which is re-fixed for the new pool by v5's own rule.

## 2. Hypotheses

**Analysis sets.** As v5 §2. P is the decisive conflicts among the 1,000 primary items (SciFact,
PopQA, FEVER). T is the decisive conflicts among the 100 TruthfulQA stratum items. P and T are never
pooled for a test. Set membership comes from the item `tier` field (`primary` → P, `tqa_stratum` → T).

**Methods named in the hypotheses.** Full definitions are in §5.2. Every method is evaluated on v6
data only.

| name | definition | identity |
|---|---|---|
| **VV/VDF** | MAJ if MAJ is verified; otherwise plurality among verified answers (ties `Random("v5-vv:"+id)`); otherwise MAJ | rule `vdf-1` over frozen VV and MAJ (§5.2) |
| **BE-G/VDF** | D if D is verified; otherwise the BE-G winner (= sel(W) if W ≠ ∅, else D) | rule `vdf-1` over the frozen BE-G output and D |
| BE-G | gated reducer `member/nei0.5/gated`, hosted checker 0.2.0 | template `99c8b9c91c27d4fcf8cb33be2f342eb6dffa175f10802459df52a23ee2a0a245` |
| BE | ungated reducer `member/nei0.1`, hosted checker 0.2.0 | template `084ecdbdcd06193beab228fc9ca21fcf1842f1fffd0326052c5b8908581dada0` |
| VV | plurality among verified answers, else MAJ (v5 §5.1) | v5 code, unchanged |
| MAJ | plurality over canonical answers, ties by `Random("v5-majority:"+id)` | v5 code, unchanged |
| D | the reducer's own plurality default (`gate.default_winner`) | v5 code, unchanged |

"Verified" means the value has at least one witness: a parsed answer with that canonical value that
carries an accepted, status-`ok`, mapped `supports` label (`evaluate_v5.supports_effective`).

**Structure (two families, each with family-wise α = 0.05):**

| family | role | contents | multiplicity control |
|---|---|---|---|
| **F1 (primary)** | the new claim: VDF on a new pool | H1a-VDF → H3a-VDF | fixed sequence, α = 0.05 (two-sided McNemar) then one-sided 0.025 (CP) |
| **F2 (replication)** | v5's hypotheses re-tested unchanged | H1a-rep, H1b-rep (Holm); H3a-rep, H3b-rep (own α each), all as v5 | exactly v5's §10 structure |
| secondary | | BE-G/VDF (H1, H3a); VV/VDF on T (H3b form); H3a-pool (BE-G only); every F1/F2 statistic under the alias grader (§3.1) | unadjusted, labelled secondary |

**Why this structure.**

- **F1 is a fixed sequence**, H1a first. A no-harm test is only informative for a rule that
  actually overturns. A rule that never departs from MAJ has c = 0 and passes H3a vacuously. Testing
  H3a-VDF only after VV/VDF is shown to beat MAJ rules out that reading. A fixed sequence controls
  the family-wise error at 0.05 with no α split, because each test runs at its full level and the
  second runs only if the first rejects. Power of the first step is about 1 (§9.4), so the sequence
  costs almost nothing.
- **F2 keeps v5's α structure unchanged.** Its purpose is to re-run v5's hypotheses exactly as
  frozen. Re-splitting α across F1 and F2 would make it a different test, and so not a replication.
- **The two families support two separate claims.** F1 supports "VDF works on a new pool". F2
  supports "v5's result replicates on a new pool". The paper never merges them into one claim (for
  example, "at least one of VDF or BE-G is safe"). So each family controls its own error rate. This
  is the standard treatment of a pre-declared replication alongside a new primary hypothesis.
- If F1 fails and F2 succeeds, or the other way round, both results are reported as they fall.
- Secondary tests carry no confirmatory claim.

### 2.1 F1, primary family: VV/VDF (fixed sequence)

**Step 1, H1a-VDF.** On P, VV/VDF is correct at a different rate than MAJ.

- H0: P(VV/VDF right, MAJ wrong) = P(VV/VDF wrong, MAJ right).
- Exact two-sided McNemar on (b, c): p = min(1, 2·min(P(B ≤ b), P(B ≥ b))), B ~ Binom(b + c, ½).
- Reject iff p ≤ 0.05. The rejection reads "better" only if b > c, and "worse" if b < c.

**Step 2, H3a-VDF.** This runs only if step 1 rejects with b > c. Otherwise it is reported
descriptively as "not tested (sequence stopped)".

- On the items of P where MAJ is right (n_R), let c = #(VV/VDF wrong).
- H0: q_r(VV/VDF) ≥ 0.05.
- Reject iff the one-sided 97.5% Clopper–Pearson upper bound on c/n_R is **below 0.05** (one-sided
  α = 0.025). **The ceiling is v5's 0.05, unchanged.**
- At n_R = 376 this needs c ≤ 10.

**Reported with F1:**

- b, c and (b − c)/N;
- the Newcombe 95% CI and the item bootstrap (10,000 resamples, seed 42);
- p̂_w and q̂_r, with Wilson CIs;
- the H4 analogue (§2.6).

**Pre-declared sensitivity, because VDF was designed on these items.** H1a-VDF and H3a-VDF are
recomputed on P **excluding the 15 v5 "design-set" items**. These are the union of the items where
BE-G, VV, BE-G/VDF or VV/VDF overturned a right MAJ or D in v5's selector study, i.e. the harm cases
that motivated VDF. Their sorted id list has sha256
`b675a5e67267d695f3dd93fd18dae360e1d1491cf56b7c4835061b1930fe3832`. The ids are:

- `v5-fever80417`, `v5-fever90151`;
- `v5-popqa145561`, `v5-popqa175943`, `v5-popqa2211064`, `v5-popqa2342806`, `v5-popqa276747`,
  `v5-popqa2797971`, `v5-popqa4686489`, `v5-popqa6297573`, `v5-popqa6297574`, `v5-popqa695490`;
- `v5-scifactdev692`, `v5-scifactdev770`, `v5-scifactdev808`.

A result that holds on all of P but not without the design set is reported as dependent on the items
that informed the rule.

### 2.2 F2, replication family: the v5 hypotheses, unchanged

These are v5 §2.1–§2.2, re-tested on v6 data with the same tests, α and Holm structure. They are
labelled "-rep".

**H1a-rep.** On P, BE-G vs MAJ, exact two-sided McNemar.

**H1b-rep.** On P, BE vs MAJ, the same test.

H1a-rep and H1b-rep form a Holm pair, family-wise α = 0.05:

1. order the p-values, p(1) ≤ p(2);
2. reject p(1) iff p(1) ≤ 0.025;
3. only then, reject p(2) iff p(2) ≤ 0.05.

"Better" requires b > c.

**H3a-rep.** On P with MAJ right, c = #(BE-G wrong). H0: q_r(BE-G) ≥ 0.05. Reject iff the one-sided
97.5% CP upper bound is < 0.05. The ceiling is unchanged, and so is the own one-sided α = 0.025.

**H3b-rep.** On T, BE-G is non-inferior to MAJ with margin −0.03. Reject iff the Newcombe 95% lower
bound is > −0.03. v5's power warning applies: a non-rejection is "not shown", not harm.

Ungated BE is reported on H3a and H3b descriptively, as in v5.

### 2.3 Secondary (pre-declared, unadjusted, no confirmatory claim)

1. **BE-G/VDF.** The H1a form against MAJ, and the H3a form (CP bound < 0.05). In v5's post-hoc
   study it was 87 / 6 against MAJ, with an H3a bound of 0.0344. In v6 it is reported next to BE-G,
   to show what VDF adds to the scored gate.
2. **VV/VDF on T.** The H3b form (Newcombe lower bound > −0.03).
3. **H3a-pool, for BE-G only.** It is declared **after** v5's H3a result was known, and the v5 half
   of its data is fixed: c₅ = 12, n_R,₅ = 376. It is reported under "pooled across two pools
   (secondary; declared after v5's H3a miss)", after H3a-rep. It is never computed for VDF: VDF has
   no v5 confirmatory data to pool, because its v5 numbers are post hoc.
   - **Estimand.** q_pool = (c₅ + c₆)/(n_R,₅ + n_R,₆) for BE-G.
   - **Exact test (decides H3a-pool).** H0: q_pool ≥ 0.05. Reject iff the one-sided 97.5% CP upper
     bound on (12 + c₆)/(376 + n_R,₆) is < 0.05. At n_R,₆ = 376 that means c₆ ≤ 13.
   - **Dependence-robust sensitivity.** The studies share items (§6), so we also compute
     U = (376·U₅ + n_R,₆·U₆)/(376 + n_R,₆), where each U is a one-sided 98.75% CP bound
     (U₅ = 0.0587). By Bonferroni, q_pool ≤ U with probability ≥ 0.975 under any dependence. The
     pool "holds robustly" iff U < 0.05, i.e. c₆ ≤ 7 at n_R,₆ = 376.
   - **Also reported:** items that are c-events in both pools, and an item-cluster bootstrap 95%
     interval of q_pool (10,000 resamples, seed 42).

### 2.4 Cross-pool consistency (descriptive)

For BE-G, BE and VV on P and T, we report the v6 − v5 differences in (b − c)/N, q̂_r and p̂_w, with
Newcombe intervals for independent proportions. These are descriptive, because of item reuse.

For VV/VDF and BE-G/VDF, the v5 side is the post-hoc selector-study value, which is labelled as
such. No test of "same effect in both pools" is made.

### 2.5 Local checker: not part of the analysis

A local checker arm with `bespoke-minicheck:7b` (checker_id `98751cc07911d57a1586848dfb8c4e7b`) was
drafted and removed before the freeze. MiniCheck is binary (`supports` or not). It met a binary
validation criterion (supports precision 0.857 FEVER / 0.918 SciFact-300, stability 1.00), but its
three-way macro-F1 is 0.499, and v5 §2.3 requires 0.70. An exploratory re-decision of the v5 data
with its labels lowered VV/VDF accuracy on P from 0.873 to 0.778 and BE-G from 0.865 to 0.776,
because correct REFUTED answers need a `refutes` label that MiniCheck never emits. Harm did not
change. The checker in a verify-then-vote gate must be three-way; v6 uses only the hosted 0.2.0
checker. Evidence: `real-agent-eval/v5/local_checker/` and
`tools/evidence/support/validation/MINICHECK_RESULTS.md` (exploratory, not hashed into the freeze).

J_local (the `mistral:latest` judge, v5 `local_judge.py` and pin unchanged) may still be run as an
exploratory, non-participant small-judge reference.

### 2.6 H4 (gate soundness) and H5 (descriptive)

H4 is as v5 §2.5 on v6 data:

- c_D, F, the F items and `harm_bound_holds` for BE-G;
- F̂ with the 0.2.0 rate 18/350.

**VDF is an instance of the same theorem.**

- **The Lean statement** (`gate_harm` / `gate_cD_le_F`) quantifies over any selector with selection
  closure. VDF's selector is sel′(S) = D if D ∈ S, else sel(S). It is closed, and sel′(P) = D
  because D ∈ P. Hence c_D(VDF) ≤ F, where F counts decisive items in which some incorrect value is
  verified.
- **For VV/VDF the default is MAJ itself.** The bound therefore holds directly against MAJ:
  c(VV/VDF vs MAJ) ≤ F. Unlike BE-G, there is no tied-plurality gap.
- **Reported:** c_D, F, the c_D items and `harm_bound_holds` for VV/VDF (against MAJ) and BE-G/VDF
  (against D), on P and T. A violation is an implementation defect.

H5 is as v5 §2.6: gap-closed fraction (now also for VV/VDF and BE-G/VDF), cost, latency, replay,
audit, majority-following, subgroups and sensitivity analyses.

## 3. Units, outcome and tests

These are identical to v5 §3:

- R = 1;
- eligible item: at least 2 parsed answers;
- disagreement item: at least 2 distinct canonical parsed answers;
- decisive conflict: eligible, with at least 1 correct and 1 incorrect parsed answer under G-AK
  (`v4/benchmark/scripts/answer_key.py`, sha256 `b3ffdbae…`);
- primary outcome: correctness of each method's selected answer on each decisive conflict;
- no clustering within a study.

### 3.1 Secondary grader: G-AK with frozen aliases

The **primary grader is unchanged**: G-AK, `answer_key.py` `b3ffdbae…`.

The secondary grader **G-AK+A** is G-AK with each PopQA item's `gold.aliases` extended by the list
for that item in `real-agent-eval/v6/tuning/aliases/aliases.json` (sha256
`77d1fce09c137647eea4a12b85dfc574d493e86fe9f79f2d1d653bb8b4ca2174`). Nothing else changes. The alias
file was built from Wikidata, blind to any agent answer or outcome
(`tuning/aliases/build_aliases.py`, `README.md`).

- **Implementation.** `items_confirmatory_aliases.jsonl` is the v5 item file with only
  `gold.aliases` extended on PopQA items. It is built deterministically and hashed at the freeze.
  `evaluate_v6.py` then runs a second time, with `--items` pointing to it, into `eval_aliases/`. The
  evaluator code is the same.
- **What is reported under G-AK+A.** Every F1 and F2 statistic: b, c, p, the CIs, H3a bounds and
  readings. G-AK+A re-derives the decisive set.
- **What decides the hypotheses.** Rejections are decided under G-AK only. G-AK+A results are
  secondary, and any F1/F2 test whose verdict differs between the graders is flagged.

## 4. Agents

### 4.1 Proposed pool (family-disjoint from v5)

**Selection criteria (fixed before any v6 data):**

1. a different model family, from a different developer than every v5 agent;
2. 2–8 B parameters, with the pool's size profile close to v5's (v5: 2.6, 3.1, 3.2, 3.8 and 7.2 B);
3. in the Ollama library as an instruct model, with a default Q4_K_M quantization like v5's;
4. not a reasoning ("thinking") model, because the answer turn is capped at `num_predict` 512;
5. a context of at least 4,096 tokens. The longest v5 answer prompt was 2,101 tokens (p99 1,713),
   plus 512 output tokens;
6. no fine-tune of a v5 family. That excludes Llama-, Qwen-, Mistral-, Gemma- and Phi-derived models,
   and the DeepSeek-R1 distills.

Ollama's `format` (JSON schema) output is grammar-constrained by the runtime for any model it
serves. Schema compliance therefore does not depend on the model. Answer quality and truncation
do, and the qualification run (§4.3) checks both.

**The pool.** Each agent takes the list position of the v5 agent of similar size. The dispatch shuffle
(`Random(20261101)`) and the SciFact retriever assignment (`Random("v5-ret:"+id)`) permute list
*positions*, so each v6 agent inherits its v5 counterpart's dispatch slots and its BM25/dense
assignment.

| list pos. | v6 agent (Ollama tag) | developer, family | params | Q4_K_M size | ctx | v5 agent in this position |
|---|---|---|---|---|---|---|
| 0 | `falcon3:3b` | TII, Falcon 3 | 3.2 B | 2.0 GB | 32K | llama3.2:3b (3.2 B) |
| 1 | `olmo2:7b` | AI2, OLMo 2 (1124 instruct) | 7.3 B | 4.5 GB | 4K | mistral (7.2 B) |
| 2 | `exaone3.5:7.8b` (pre-declared alternate; see §4.3 outcome) | LG AI Research, EXAONE 3.5 | 7.8 B | 4.8 GB | 32K | gemma2:2b (2.6 B) |
| 3 | `nemotron-mini:4b` | NVIDIA, Nemotron (Minitron) | 4.2 B | 2.7 GB | 4K | phi3:mini (3.8 B) |
| 4 | `granite3.3:2b` | IBM, Granite 3.3 | 2.5 B | 1.5 GB | 128K | qwen2.5:3b (3.1 B) |

The pool totals about 15.5 GB, against v5's 12.1 GB, and loads concurrently on the same 36 GB
M3 Pro as v5. Tags and sizes were checked on the Ollama library pages on 2026-10-24.

**Rationale per agent.**

- **falcon3:3b.** TII's Falcon 3 was trained from scratch, with the 3B pruned and distilled from
  the 7B. It is a strong small instruct model on knowledge QA, unrelated to any v5 family.
- **olmo2:7b.** AI2's fully open model, with open data and code. It is the 7B anchor in mistral's
  role. Its 4K context equals `num_ctx` 4096; the v5 prompts leave about 1.4K tokens of headroom.
- **exaone3.5 (2.4b chosen, 7.8b used).** LG's bilingual (English/Korean) instruct model. It adds a
  non-US training lineage. The 2.4b was chosen at gemma2:2b's size; it failed qualification and its
  first pre-declared alternate, the 7.8b, holds the position (§4.3 outcome). Licence: EXAONE AI Model
  License 1.1 (non-commercial; research use).
- **nemotron-mini:4b.** NVIDIA's Minitron-derived model, tuned for RAG QA and function calling,
  which fits a grounded-citation task. Its 4K context has the same headroom note as olmo2.
- **granite3.3:2b.** IBM's Apache-2.0 enterprise model, tuned for RAG and instruction following.
  Its thinking mode is off by default and must stay off; no `think` flag is sent.

**Pre-declared alternates, in order, per list position.** An alternate is used only if the agent fails
qualification (§4.3).

| list pos. | alternates in order |
|---|---|
| 0 | `falcon3:7b`, then `command-r7b` (Cohere, 7B, 8K) |
| 1 | `command-r7b`, then `aya-expanse:8b` (Cohere, 8B, 8K) |
| 2 | `exaone3.5:7.8b`, then `aya-expanse:8b` |
| 3 | `command-r7b`, then `aya-expanse:8b` |
| 4 | `granite3.3:8b`, then `command-r7b` |

- At most one Cohere model may be in the pool. If a second slot needs one, the study stops for an
  amendment.
- `command-r7b` and `aya-expanse` carry non-commercial licences, as EXAONE does.

**Fallback pool, if the author prefers version-disjoint over family-disjoint.** This is not
recommended, because it tests a weaker claim: same developers, newer versions. The pool would be
`llama3.1:8b`, `ministral-3` (or `mistral-nemo` if too large), `gemma3:4b`, `phi4-mini:3.8b` and
`qwen2.5:7b` / `qwen3` with thinking off. Verify every tag on the library page before using it.

**Slots to fill at pull time.** Filling them is not an amendment.

Filled 2026-10-24 from the installed models (all Q4_K_M; per-model parameter size,
`api_show_modelfile_sha256` and licence head are in `pool_manifest.json`, hashed below):

- falcon3:3b `784a7eab5b891a30c0b57300c1c6da7022b02665fc5a12c1c817650575c10917`
- olmo2:7b `4208d3b406db076e1569c97a2fb67cf9c86b845544c1a61ff218259daf9e3538`
- exaone3.5:7.8b `c7c4e3d1ca22fe9225f18b35eb719f67e2ca96a42e7fd17294a45b83ba8fbf03`
- nemotron-mini:4b `ed76ab18784f5a01c9ec5b3c250e964d4f9c7a983e59ba041bb995f0fe2e8fb3`
- granite3.3:2b `07bd1f170855240f9e162bf54ea494a8bc1c73d8cbd1365d7fccbeb7d2504947`
- embedder nomic-embed-text `0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f` (equals v5's)
- `pool_manifest.json` sha256 `37f491ce75726ab06fdfb3a84b8651c6b043cd8f3d061aa3e98c8b3c296f82b1`

### 4.2 Agent protocol (identical to v5 §4.1)

- Temperature 0.7, seed 42, dispatch seed 20261101, `num_ctx` 4096;
- Ollama **0.17.7** (installed and unchanged), `OLLAMA_NUM_PARALLEL=1`, and a quiet machine;
- query turn: question only, MC options hidden, at most 12 words, `num_predict` 32;
- retrieval: fever17 uses BM25 with k = 5; SciFact uses BM25 or dense by `Random("v5-ret:"+id)`;
  sealed as `bran-retrieval/1`. The embedder is nomic-embed-text;
- answer turn: Ollama structured output (`v5/schema/answer_v5.schema.json`), citations restricted
  to the shown labels (at most 3), `num_predict` 512;
- the grounded fleet; no mixed-fleet arm;
- prompts, schemas and fragments: the v5 files, byte-identical (hashes in §12).

All seed **strings** keep their `v5-` prefixes (`v5-majority:`, `v5-ret:`, `v5-vv:`, `v5-cv:`,
`v5-conf:`, `v5-jregen`, `v5-loao`, `v5-witness-sample`). They are part of the frozen code, and
renaming them would be a change of method.

### 4.3 Pool qualification on the v5 dev items (before the freeze; local only)

This step runs the new pool through `collect_v6.py --split dev` on the 160 v5 dev items. That takes
about 1.1 h of local time. It makes no hosted calls. Dev data are never pooled with confirmatory
data and are not used for any test.

**Per-agent criteria (all gold-blind):**

- **Q1.** Parse failure < 0.05. This is v5's dev-gate threshold. Parse status comes from
  `collect_v5.py audit`.
- **Q2.** Answer-turn truncation (`done_reason` = `length`) < 0.05. Also, no answer-turn prompt with
  `prompt_eval_count` + 512 > 4096.
- **Q3.** At least one valid citation on ≥ 0.25 of parsed answers. An agent that never cites cannot
  be verified. The lowest v5 dev rate was gemma2:2b's 60/160 = 0.375.

**Pool criteria (G-AK-graded, as v5's dev gate):**

- **Q4.** Yield (decisive/eligible) ≥ 0.30.
- **Q5.** Majority-wrong share m ≥ 0.20.

**Rules.**

- If an agent fails Q1–Q3, it is replaced by its first alternate (§4.1). Q1–Q3 are re-run for the
  replacement only, and Q4–Q5 for the pool.
- If Q4 or Q5 fails for the qualified pool, v6 stops before the freeze and is reported as "pool did
  not produce enough conflicts". There is no mixed-fleet arm.
- **BEST.** BEST is the agent with the most G-AK-correct answers on the 160 dev items, with ties by
  list order. This is v5's rule (`max(sorted(per_agent), key=correct)`). It is recorded in
  `FREEZE.json` and passed to the evaluator as `--best-model`. It is a descriptive baseline only.

**Qualification outcome (2026-10-24, 160 dev items, local, no hosted call).**

- First run: `exaone3.5:2.4b` failed Q1 (160/160 request errors). Ollama 0.17.7's model runner
  stopped on every request (HTTP 500), also with no other model loaded. The other four agents passed.
- Its first alternate, `exaone3.5:7.8b`, replaced it. The dev collection was re-run for the whole
  pool, because Q4–Q5 and BEST need every agent's answers.
- Second run: every agent passes Q1–Q3 (parse failures 0, truncation 0; citing rate 1.00 falcon3,
  0.62 olmo2, 0.72 exaone3.5:7.8b, 0.56 nemotron-mini, 0.99 granite3.3). Pool: Q4 = 98/160 =
  0.61, Q5 = 32/98 = 0.33. Both pass.
- BEST = `exaone3.5:7.8b` (119/160 correct; next olmo2 94, granite3.3 96).
- Records: `results/dev/qualification_v6.json`; the failed run is kept in
  `results/dev_failed_exaone2.4b/`.

## 5. Methods

### 5.1 Methods carried over from v5

Identical to v5 §5 for MAJ, BE-G, BE, B0, EO, VV, D, CV, CONF, BEST, J, RS, CB-S and ORC:

- same definitions, templates, tie seeds and judge rules;
- no local-checker method is run (§2.5).

### 5.2 New in v6: verified default first (rule `vdf-1`)

For one eligible item, define:

- **W.** The set of canonical values that have at least one witness: a parsed answer with that value
  carrying an accepted (checker `f2a14bd8…`), status-`ok`, mapped `supports` label. This is
  `evaluate_v5.supports_effective`, the same set the BE-G gate and VV use.
- **MAJ.** v5's majority value, with ties by `Random("v5-majority:"+id)`.
- **VV.** v5's verified vote: plurality among answers whose value is in W, with ties by
  `Random("v5-vv:"+id)`; MAJ if W = ∅.
- **D.** The frozen reducer's plurality default, `gate.default_winner`, from the BE-G run of the
  frozen binary.
- **BE-G.** The frozen binary's BE-G winner. This is sel(W) if W ≠ ∅, else D.

Then:

```
VV/VDF   = MAJ                           if MAJ ∈ W
         = VV   (= plurality over W)      if MAJ ∉ W and W ≠ ∅
         = MAJ                           if W = ∅
BE-G/VDF = D                             if D ∈ W
         = BE-G (= sel(W))                if D ∉ W and W ≠ ∅
         = D                             if W = ∅
```

Equivalently, VV/VDF = MAJ if MAJ ∈ W, else VV; and BE-G/VDF = D if D ∈ W, else BE-G. Membership
compares canonical values (`norm_obj`), as the evaluator does. Single-value items return their only
value.

**Implementation.** `v6/vdf_v6.py`:

- it is a pure function of the evaluator's per-item records (MAJ, VV, W, the BE-G winner and D), all
  computed by the frozen `evaluate_v5.py` and binary;
- it needs no new policy template, no reducer call and no Rust change;
- its replay identity is trivial, because it is deterministic over sealed labels.

**Reproduction gate (pre-freeze, binding).** Run on the v5 confirmatory data, `vdf_v6.py` must
reproduce `v5/selector_study/results.json` (`bbb39957…6d81`) exactly, per item and in aggregate:

- VV/VDF on P: acc 0.8726, b/c vs MAJ 87 / 4, H3a bound 0.0270;
- BE-G/VDF on P: acc 0.8688, b/c 87 / 6, c_D 4, bound 0.0344;
- on T: VV/VDF 6 / 1 and BE-G/VDF 9 / 1.

This run reads only already-unblinded v5 data and makes no model call.

**Hosted checker.** 0.2.0, `checker_id` `f2a14bd8988371bd231ca6ff137be13e`, Claude Code CLI **2.1.307**
(pinned binary, `DISABLE_AUTOUPDATER=1`, as v5 RUN_NOTES note 1). `accepted_checkers` is exactly
`[f2a14bd8988371bd231ca6ff137be13e]`.

**Judges.** J `4f8c27d90e3c1230dd9b9a91d30530f1`, RS `108a3dee08e1b4286ea879ee070ce4bb` and CB-S
`1de78d843c35f57cfa9d2ebfd708f681`, all unchanged.

**Cached labels are authoritative.** A (proposition, passage) pair already checked in v5 is not
checked again. The sealed v5 label is used, exactly as v5 reused its futility-look labels (RUN_NOTES
note 2). The same holds for CB-S decisions on items whose closed-book prompt is byte-identical; CB-S
does not depend on the agents. J and RS see the agents' answers, so they are always called fresh.

## 6. Items: reuse the v5 confirmatory 1,100

**Decision (recommended).** v6 collects the same 1,100 items as v5:

- `v5/benchmark/items_confirmatory.jsonl`, `v5-benchmark-1.1.0`, sha256 `38987c42…1a83`;
- frozen `order` 0–1,099, `--n-items 1100`;
- P = SciFact 250 + PopQA 400 + FEVER 350, T = the 100-item TruthfulQA stratum;
- sorted id-set sha256 `d649d362afe2848921318319adf7a438e0f8cde7cdf983017323e2f24bed19a5`.

**Why reuse rather than draw fresh items from `reserve_order.json`:**

1. **It isolates the factor under test.** With the same items, a v5–v6 difference is a pool
   difference. With fresh items, the pool and the item sample change together, and a replication
   failure could not be attributed.
2. **The fresh pool cannot reproduce P's composition.** SciFact's fresh pool was 275 claims, and v5
   used 250. Only 25 SciFact items remain in the reserve, against 250 in P. SciFact is where BE-G's
   effect was largest (33/2), and SciFact REFUTED was 19/0. A fresh P would be about 97% PopQA and
   FEVER, which is a different estimand.
3. **Fresh items need new frozen code.** That means a `v6-benchmark` build with records for reserve
   ids, new exclusion proofs and a gold-consistency check. That is more surface to freeze and audit,
   for no gain in the hypotheses' scope.
4. **Cost.** Shared (proposition, passage) labels and CB-S decisions are cached (§8.8). The
   estimated hosted cost falls from about $64 to about $43.

**What reuse costs (disclosed in §13):**

- **The authors have seen v5's per-item outcomes on these items.** Nothing in v6 can be tuned to
  them. Every method, template, threshold, checker and prompt is frozen from v5, which was selected
  on v5 dev. The pool was chosen by the criteria in §4.1, without looking at v5 item outcomes. The
  one v6 choice made on data, BEST, is made on dev.
- **The two studies share items.** v6 generalises across agent pools, not across item samples.
  v5 and v6 estimates are positively correlated. That is why H3a-pool carries a dependence-robust
  sensitivity bound (§2.3), and why cross-pool comparisons are descriptive (§2.4).
- **VDF was designed on these same items' v5 outcomes.** The selector study's own README says a
  variant "can become confirmatory only through a new preregistered run on fresh items". v6 meets
  "new run" (a new pool, so new answers, new conflicts and new citations) but not "fresh items".
  - **Mitigation.** The pre-declared design-set exclusion (§2.1) drops the 15 items whose v5 harm
    cases motivated VDF.
  - **Accepted residual risk.** If the conflicts that VDF fixes recur on the same items in a new pool
    (hard PopQA entities, SciFact claims with two verified values), v6 overstates VDF's benefit
    relative to fresh items.
  - **The author's choice.** This is an explicit decision (SUMMARY). The alternative is a fresh-item
    run with a PopQA/FEVER-only P (see "Alternative" below).
- **Reused checker labels.** If a v5 label is a false support, v6 inherits it on any pair the new
  pool also cites. This correlates the two studies' F counts (H4). We report the share of v6 checks
  that were cache hits, and F split into inherited and new labels.

**Alternative, if the author rejects reuse.** Draw a fresh set from the v5 1.0.0 uncollected items
and the reserve: TruthfulQA 200 + 160 uncollected, PopQA 133 extension + `reserve.popqa[150:]`, FEVER
107 extension + `reserve.fever[150:]`, and SciFact only the 25 reserve items. It would need a
`v6-benchmark` builder with exclusion proofs against all v5 items and every validation slice. The
hosted cost is then about $64 with no cache, and H3a's estimand moves to PopQA and FEVER.

## 7. Metrics

These are identical to v5 §7: accuracy, b/c, p_w and q_r; gap-closed fraction; the uniform cost
basis on every disagreement item; latency; replay; audit size; majority-following; and the
"also reported" list. There are two additions.

**Cost with caching.** For BE-G, BE and VV, the $ per decision is reported twice:

- **(i) marginal.** Only the live calls made in v6.
- **(ii) full-label.** Each label is priced at its original call cost, from the v5 and v6
  `check_calls.jsonl` logs. This is the cost basis comparable to v5's corrected figure (v5 RUN_NOTES
  note 9). It is also the one the paper quotes.

**Cache share.** The fraction of v6 cited checks and gold-shown checks that were v5 cache hits.

## 8. Collection and check protocol

1. **Environment.** As v5 §8.1. The v6 collector (`collect_v6.py`, §11) verifies the v6 model
   digests against `v6/pool_manifest.json`. It also checks the corpus and index hashes, the dense
   manifest and `v6/FREEZE.json` at start-up, and aborts on any mismatch.
2. **Collection.** `collect_v6.py --split conf --n-items 1100 --out real-agent-eval/v6/results/conf`.
   - It resumes from the next uncollected item after a crash. Completed items are never re-run.
   - **One non-binding futility look**, as v5 §8.2, now on the **F1 primary method**. After the first
     300 items in frozen order, `futility_v6.py` computes VV/VDF vs MAJ on the decisive P conflicts
     among them, and reports only b and c. It runs the frozen BE-G reduction only because D is needed
     for the H4 check. No BE-G b or c is reported.
     - If b − c ≤ 0 for VV/VDF, collection stops for futility.
     - Otherwise it continues to 1,100, with no further looks.
     - α is unchanged.
3. **Captures.** Into a v6 evidence cache **seeded by an APFS clone of the v5 confirmatory cache**.
   The v5 cache is never written to.
4. **Hosted checks.** `run_checks_v5.py … --out v6/results/conf --cache v6/results/conf/evidence-cache
   --expect-checker f2a14bd8988371bd231ca6ff137be13e`. Gold-shown diagnostic checks are run as in v5
   (`--gold-scope decisive --gold-restrict fever,scifact`).
5. **Local checks.** None; the MiniCheck arm was removed before the freeze (§2.5).
6. **Judges.** J, RS and CB-S run on all disagreement items. The CB-S store is seeded by a clone of
   v5's `judge-store-cbs`. Then the J regeneration (200 items) and the LOAO subsample (50) run, and
   J_local optionally (exploratory).
7. **Analysis.** `evaluate_v6.py` (a wrapper over the frozen `evaluate_v5.py`, §11) runs **once**
   with the frozen binary and `vdf_v6.py`. Then `make_results` and `pooled_h3a_v6.py` (§2.3–§2.4)
   run. `RESULTS.md`
   gives the preregistered analyses first, then deviations, then exploratory analyses.
8. **Stopping.** There is no extension. I = 1,100 is fixed by item reuse. The v5 stopping rule
   (§9 there) gave I = 1,000 P items, and v6 keeps that.
9. **Budget.** The author is asked to approve a cap of **$60**. The central estimate is ≈ $43
   (RUN_PLAN.md), and `--max-usd` stays on the check step.

## 9. Sample size and power (`power/power_v6.py`, `power/power_results_v6.json`)

All numbers are exact. They use binomial sums and the same Clopper–Pearson bisection as
`evaluate_v5.cp_upper`, with no simulation. The script asserts v5's c_max(376) = 10 and the v5
bounds 0.0551 and 0.0904.

Numbers for F1 (VV/VDF) are in §9.4. §9.1–§9.3 cover F2 (the BE-G replication) and H3a-pool.

### 9.1 H1a-rep (BE-G)

v6 will have about 526 decisive P conflicts if the new pool's yield matches v5's. The table gives
exact McNemar power, as P(reject and b > c).

| N decisive | scenario (ψ, Δ) | power at α = 0.025 (Holm step 1) | at α = 0.05 |
|---|---|---|---|
| 526 | v5 observed (0.196, 0.150) | 1.000 | 1.000 |
| 526 | half v5's effect (0.196, 0.075) | 0.949 | 0.972 |
| 526 | v5 planning point (0.25, 0.075) | 0.876 | 0.925 |
| 450 | half effect | 0.908 | 0.946 |
| 400 | half effect | 0.867 | 0.917 |

### 9.2 H3a-rep (BE-G), v6 alone (ceiling 0.05, one-sided α = 0.025)

c_max is the largest c that rejects: 7 at n_R = 300, 9 at 340, **10 at 376**, 11 at 410 and 13 at 450.
The table gives the probability of passing.

| n_R | q = 0.0319 (v5) | q = 0.025 | q = 0.020 | q = 0.0167 (v5 dev) | q = 0.010 |
|---|---|---|---|---|---|
| 300 | 0.257 | 0.524 | 0.745 | 0.868 | 0.989 |
| 340 | 0.354 | 0.654 | 0.852 | 0.939 | 0.997 |
| **376** | **0.344** | **0.659** | **0.863** | **0.947** | 0.998 |
| 410 | 0.341 | 0.669 | 0.875 | 0.955 | 0.999 |
| 450 | 0.424 | 0.760 | 0.928 | 0.979 | 1.000 |

**Honest reading.** If the new pool's BE-G harm rate equals v5's 0.032, v6's H3a passes with
probability about **one in three**. Integrating over the v5 posterior for q (Jeffreys,
Beta(12.5, 364.5)), the predictive pass probability at n_R = 376 is **0.37**. H3a is well
powered only if the true rate is near 0.02 or below.

Reaching 80% power at q = 0.032 needs n_R ≈ 1,050. That is about 2,800 P items at v5's 0.376 right
majorities per item, which the benchmark cannot supply (§6). A replication of this size is
therefore not a reliable way to "fix" H3a. Its value is a second independent estimate of q_r, and
the pooled test.

### 9.3 H3a-pool (secondary, BE-G only), with v5 fixed at 12/376

**Exact pooled test.** It rejects iff 12 + c₆ ≤ c_max(376 + n_R,₆).

| n_R,₆ | total n | c₆ allowed | q = 0.0319 | q = 0.025 | q = 0.020 | q = 0.0167 | q = 0.010 |
|---|---|---|---|---|---|---|---|
| 300 | 676 | ≤ 10 | 0.637 | 0.865 | 0.959 | 0.987 | 1.000 |
| 340 | 716 | ≤ 12 | 0.707 | 0.912 | 0.979 | 0.995 | 1.000 |
| **376** | **752** | **≤ 13** | **0.683** | **0.907** | **0.979** | **0.995** | 1.000 |
| 410 | 786 | ≤ 15 | 0.759 | 0.944 | 0.991 | 0.998 | 1.000 |
| 450 | 826 | ≤ 16 | 0.726 | 0.937 | 0.990 | 0.998 | 1.000 |

The predictive pass probability (v5 posterior, n_R,₆ = 376) is **0.62**. At every n_R,₆ in the grid,
the c₆ allowed by the pooled test is at least v6's own c_max. A v6 H3a pass therefore implies a
pooled pass.

**Dependence-robust pooled bound (sensitivity).** U₅ = 0.0587.

| n_R,₆ | c₆ allowed | q = 0.0319 | q = 0.025 | q = 0.020 | q = 0.0167 | q = 0.010 |
|---|---|---|---|---|---|---|
| 300 | ≤ 4 | 0.036 | 0.129 | 0.282 | 0.439 | 0.816 |
| 376 | ≤ 7 | 0.086 | 0.276 | 0.521 | 0.707 | 0.963 |
| 450 | ≤ 9 | 0.090 | 0.311 | 0.587 | 0.778 | 0.983 |

The predictive probability is 0.15. The robust bound is conservative because it spends half of α on
v5, whose own bound is already above 0.05. It is a sensitivity analysis and does not decide
H3a-pool.

### 9.4 F1: VV/VDF

**The planning inputs are post hoc.** They come from v5's selector study: b = 87, c = 4 of N = 526,
and H3a c = 4 of n_R = 376. VDF was chosen because it looked good on these data, so they are
optimistic, and the 0.02 and 0.03 rows matter more than the 4/376 row.

**H1a-VDF, step 1** (exact McNemar; F1 tests it at α = 0.05).

| N decisive | scenario (ψ, Δ) | power at α = 0.05 | at α = 0.025 |
|---|---|---|---|
| 526 | v5 post hoc, b 87 / c 4 (0.173, 0.158) | 1.000 | 1.000 |
| 526 | half the effect, same ψ (0.173, 0.079) | **0.992** | 0.984 |
| 526 | half of both b and c (0.087, 0.079) | 1.000 | 1.000 |
| 450 | half the effect, same ψ | 0.981 | 0.964 |
| 400 | half the effect, same ψ | 0.967 | 0.940 |

**H3a-VDF, step 2** (CP bound < 0.05; c_max as in §9.2).

| n_R | q = 0.0106 (4/376, post hoc) | q = 0.020 | q = 0.030 |
|---|---|---|---|
| 300 | 0.984 | 0.745 | 0.320 |
| 340 | 0.996 | 0.852 | 0.431 |
| **376** | **0.997** | **0.863** | **0.425** |
| 410 | 0.998 | 0.875 | 0.426 |
| 450 | 1.000 | 0.928 | 0.517 |

**The whole sequence.** We need P(step 1 rejects and step 2 rejects). Its Bonferroni lower bound,
P(H3a) − (1 − P(H1a)), uses the weakest N = 526 H1a scenario. It is **0.99 / 0.855 / 0.417** at
q = 0.0106 / 0.02 / 0.03, with n_R = 376.

The predictive pass probability of H3a-VDF, under q ~ Beta(4.5, 372.5) from the post-hoc v5 count, is
0.96. It is optimistic for the reason above.

**Honest reading.** H1a-VDF is essentially certain if VDF keeps even half of its post-hoc gain. Whether
H3a-VDF passes depends on the new pool's true harm rate:

- near-certain at q ≈ 0.01;
- about 0.86 at 0.02;
- about 0.43 at 0.03, which is roughly BE-G's v5 rate.

The two v5 harm mechanisms that VDF does *not* remove (an unverified right default against a
verified wrong minority) produced 4 of 376 in v5. Their rate under a new pool is the main uncertainty.

## 10. Multiple comparisons

| family | contents | control |
|---|---|---|
| **F1 (primary)** | H1a-VDF → H3a-VDF (VV/VDF) | fixed sequence: McNemar at α = 0.05, then CP one-sided 0.025 only if step 1 rejects with b > c; family-wise α = 0.05 |
| **F2 (replication)** | H1a-rep, H1b-rep (BE-G, BE) | Holm, family-wise α = 0.05 (as v5) |
| F2 (replication) | H3a-rep, H3b-rep (BE-G) | own one-sided α = 0.025 each (as v5) |
| secondary | BE-G/VDF H1 and H3a forms; VV/VDF on T; H3a-pool (BE-G) | unadjusted, labelled secondary; the H3a-pool robust bound is a sensitivity |
| H4, H5, §2.4, references | | descriptive; Holm-adjusted p reported for the reference family vs MAJ |

- F1 and F2 support separate claims and are never combined (§2). Neither family is used to rescue
  the other.
- H3a-pool is not used to rescue H3a-rep. Both are reported as they fall, in the order H3a-rep, then
  H3a-pool.
- The paper's results order is: F1, F2, secondary, descriptive, exploratory.

**Sensitivity analyses.** As v5 §10:

- null judge decisions scored wrong;
- PopQA excluded;
- MAJ with earliest-arrival ties;
- c and q_r against D;
- the blinded 100-witness sample.

Three are added:

- the cache-hit split of F (§6);
- the dependence-robust H3a-pool bound;
- F1 without the 15 design-set items (§2.1).

## 11. Analysis code path

No v5 file is edited. The v6 code consists of thin wrappers that load the frozen v5 modules by path
and override module constants only. They are written, tested on the dev qualification data and on
v5's `--synthetic-test` fixtures, and hashed **before** the freeze.

| file | what it overrides | why |
|---|---|---|
| `v6/collect_v6.py` | `MODELS` (the v6 list, §4.1); `V3_MANIFEST` → `v6/pool_manifest.json`; `FREEZE` → `v6/FREEZE.json`; `CONF_FROZEN` += the v6 files; requires `--out` under `v6/results/` | `collect_v5.verify_digests` aborts unless the digests equal `v3/results/run_manifest.json`, which holds the v5 pool; the default `--out` is v5's results dir |
| `v6/pool_manifest.json` | `{"model_digests": {tag: {"digest": …}}}`, written from `/api/tags` at pull time | the digest reference |
| `v6/post_collect_v6.py` | `OUT` → `v6/results/conf`; `step_checks` passes `--out` and `--cache` to `run_checks_v5.py`; seeds the cache and CB-S store by clone | `post_collect_v5` hardcodes `v5/results/conf`, and `run_checks_v5` defaults to it |
| `v6/evaluate_v6.py` | `PREREG_BEST` → the v6 BEST (§4.3); verifies `v6/FREEZE.json`; calls `evaluate_v5.main(argv)`; then calls `vdf_v6.run(...)` on the same inputs and writes `evaluation_v6_vdf.json` (F1, the BE-G/VDF secondary, the VDF H4 rows and the design-set sensitivity). It refuses the local-checker flags (§2.5). Finally it re-runs every F1/F2 statistic under G-AK+A (§3.1) | the conf guard aborts unless `--best-model` equals `PREREG_BEST` (v5: `"mistral"`); v5's evaluator has no VDF |
| `v6/vdf_v6.py` | new; §5.2 rule `vdf-1`. It rebuilds items with `evaluate_v5.prepare_item`, takes W from `evaluate_v5.supports_effective`, and takes MAJ, VV, D and BE-G from the evaluator's `paired_decisions_v5.csv`. It asserts its own BE-G and D against `evaluate_v5.mirror`. Tests use `mcnemar_p`, `newcombe_paired`, `cp_upper` and `wilson` from `evaluate_v5` | derived from `v5/selector_study/selector_study.py` (`92a3cdab…`); the reproduction gate is in §5.2 |
| `v6/futility_v6.py` | new; the futility look on VV/VDF (§8.2), reporting b and c only | the frozen `futility_look.py` computes BE-G |
| `v6/make_results_v6.py` | the BEST label string | `make_results.py` hardcodes "mistral, fixed on dev" in a label |
| `v6/pooled_h3a_v6.py` | new: reads the v5 and v6 `evaluation_v5.json` H3a blocks and computes §2.3–§2.4 | new secondary analysis |
| `v6/qualify_v6.py` | new: Q1–Q5 and BEST on the dev run (§4.3), from raw records, `collect_v5 audit` and G-AK | pool qualification |

`evaluate_v5.py`'s own guard still requires that its hash equals v5's `FREEZE.json` entry
`9aa8fb2d…6893` and that the binary is `af420a5d…045e`. Both are unchanged.

## 12. Frozen artifacts

### 12.1 Reused from v5, byte-identical

Every entry of `real-agent-eval/v5/FREEZE.json` → `sha256` (56 files) is reused unchanged. Each was
re-hashed on 2026-10-24 and all 56 match. v6's `FREEZE.json` lists them again under the same keys.
They are the following:

- **Harness, prompts and schemas.**
  - `v5/collect_v5.py` `526bd20a…`
  - `v5/prompts/system_v5.txt` `21dc0b8a…`
  - `v5/prompts/query_v5.txt` `5e34b8a5…`
  - `v5/prompts/answer_v5.txt` `c17d013c…`
  - `v5/prompts/fragments_v5.json` `649a620a…`
  - `v5/schema/query_v5.schema.json` `f9a807f3…`
  - `v5/schema/answer_v5.schema.json` `8ddf4a78…`
- **Items.**
  - `v5/benchmark/items_confirmatory.jsonl` `38987c42…`
  - `items_dev.jsonl` `bdd0589b…`
  - `reserve_order.json` `b5ce52ef…`
  - `manifest.json` `9eec172d…`
  - `exclusion_proofs.json` `cf02e767…`
  - `build_benchmark_v5.py` `f8068e13…`
- **Corpus and retrieval.**
  - `tools/corpus/corpus_manifest.json` `2f8e8cb0…`
  - `retrieve.py` `dad5616c…`
  - `build.py` `40ef9d75…`
  - `corpus-cache/scifact_dense/dense_manifest.json` `7aef2f34…`
- **Checker 0.2.0.**
  - `tools/evidence/support/check.py` `4600f6da…`
  - `prompt_template.txt` `41c493e1…`
  - `pin.json` `8237c253…`
  - `propositions.py` `bb37f92e…`
  - `run_checks_v5.py` `6e274d04…`
  - the validation report `f2a14bd8….json` `7e4d2ba7…` and its slices
- **Captures.** `corpus_capture.py` `1dca391f…`, `capture.py` `84d9fee4…`, `canonical.py` `6d154b26…`
  and `extract.py` `7fafe904…`.
- **Judges.**
  - `tools/judge/judge.py` `eb100724…`
  - `prompt_J.txt` `38bc4bfd…`
  - `prompt_RS.txt` `c31cf927…`
  - `pin.json` `e1cd767b…`
  - `prompt_CBS.txt` `3ee5d3e4…`
  - `closed_book.py` `c5c92eff…`
  - `local_judge.py` `3a326499…`
  - `local_pin.json` `ff6d9473…`
- **Grader and canonicalizer.** `v4/benchmark/scripts/answer_key.py` `b3ffdbae…` and
  `v4/canon/canon.py` `a33b4e33…`.
- **Evaluator and binary.**
  - `v5/evaluate_v5.py` `9aa8fb2d…`
  - `v5/make_results.py` `bb0ef07d…`
  - `v5/frozen-bin/bran` `af420a5d…045e`. It is git-ignored and must still be present locally.
- **Power code.** `v5/power/power_v5.py` and `v4/power/power.py`.
- **v5 design documents.** `v5/PREREGISTRATION.md` `2609b3ab…`, `v3/GATE_SPEC.md`, `v3/FRAMING.md`
  and `v3/PREREG_DECISIONS.md`.

**Also listed, not in v5's `FREEZE.json`:**

- `v5/FREEZE.json` `8dc8b09cbcf49ea406339abcbc1a80335efe9eae32133928ae1cdcb1e6c504b6`;
- `v5/post_collect_v5.py` `ff255e962b462ec55f6d59380ef0c94365e969949a5f1bd7edaaa17b6f36772c`;
- `v5/futility_look.py` `8f62a03918ce4f4ce1d4814da218843a81fa2eeba7962c09f00fa2cbcbcd75e2`;
- the v5 confirmatory H3a input to H3a-pool: `v5/results/conf/eval/evaluation_v5.json`, hashed at
  the freeze, with c = 12 and n_R = 376;
- the alias grader: `real-agent-eval/v6/tuning/aliases/aliases.json`
  `77d1fce09c137647eea4a12b85dfc574d493e86fe9f79f2d1d653bb8b4ca2174`;
- the VDF source study:
  - `v5/selector_study/selector_study.py` `92a3cdab5318c0b2600aa1756cde6e49fb7393221d929ab311aacbc51cd5544a`;
  - `results.json` `bbb3995742e4b478b470d622869392f8acf5c1e713a30803cddf730a1fc06d81`;
  - `README.md` `509fc76093af1ccf80e44aae8e1bb3954e6db79be865ac9e602fd4266b9142d5`.

**Identities (unchanged from v5).**

| identity | value |
|---|---|
| checker_id | `f2a14bd8988371bd231ca6ff137be13e` |
| `checker_tool_version` | `0.2.0+8946ec3b8842.1f3b2cf3404e.fb4c5d09fa695.cli2.1.307` |
| J judge_id | `4f8c27d90e3c1230dd9b9a91d30530f1` |
| RS judge_id | `108a3dee08e1b4286ea879ee070ce4bb` |
| CB-S judge_id | `1de78d843c35f57cfa9d2ebfd708f681` |
| BE-G template | `99c8b9c9…a245` |
| BE template | `084ecdbd…dada0` |
| EO template | `75ee3a54…7ac7` |
| B0 template | `e08f2ea6…5f16` |
| F̂ rate | 18/350 |
| seeds | agents 42, dispatch 20261101, benchmark 20261201, bootstrap 42 |

### 12.2 New in v6

- `v6/PREREGISTRATION.md` (this file);
- `v6/pool_manifest.json` and the five digests;
- `collect_v6.py`, `post_collect_v6.py`, `evaluate_v6.py`, `vdf_v6.py`, `futility_v6.py`,
  `make_results_v6.py`, `pooled_h3a_v6.py` and `qualify_v6.py`;
- the VDF reproduction report on v5 data (`results/vdf_reproduction_v5.json`, §5.2);
- `power/power_v6.py`;
- the qualification report `results/dev/qualification_v6.json`;
- `BEST_agent`.

`FREEZE.json` → `pending` lists whatever is still missing. `collect_v6.py --split conf` refuses to
start while `pending` is non-empty.

## 13. Disclosures

1. **The study is motivated by v5's results.** It was designed after v5's H1a passed and its H3a
   missed by 0.0051 on the bound, and after the post-hoc selector study.
2. **The VDF rule was designed after seeing v5's confirmatory data.** That includes the harm cases
   of BE-G and VV (`v5/selector_study/README.md`, which says so itself), and the choice of VDF from
   among about 20 post-hoc variants because it removed harm cheaply.
   - **That is why VDF is tested only on v6's new pool**, and why its v5 numbers are never called
     confirmatory, pooled or used as evidence for it.
   - **Promoting VV/VDF to the v6 primary is itself a data-informed choice.** The v5 primary, BE-G,
     is kept unchanged as the replication family (F2).
   - **The items are the same as v5's** (§6). The design-set exclusion (§2.1) is the pre-declared
     check on item-level overfitting.
3. **H3a-pool is declared after v5's data are known**, and its v5 half is fixed. It is therefore
   secondary, BE-G only, and is reported after H3a-rep.
4. **The items are reused, and the authors have seen v5 outcomes on them** (§6). No v6 parameter
   other than the VDF rule (item 2) was chosen with knowledge of them.
5. **The pool was chosen by the criteria in §4.1** before any v6 output existed. Alternates are
   pre-declared. BEST is chosen on dev by v5's rule.
6. **Shared checker labels and CB-S decisions with v5** (§5, §6). This correlates the studies'
   F counts and CB-S rows.
7. **Inherited from v5 and unchanged:**
   - the TruthfulQA switch and the stratum;
   - the 5 FEVER same-text collisions with `fever_slice_fresh2`, 3 of them in the 1,100;
   - G-AK's known PopQA bias;
   - the hosted check records carry no token counts;
   - the J/RS rows carry no judge_id;
   - the CLI pin.
9. **Tuning screens run before the freeze** (all on v5 data):
   - checker-label threshold: screened, **dropped**;
   - discriminative support: screened, **dropped**;
   - tie rule: screened, **unchanged**;
   - checker-wording stability test: **exploratory**. The flip rate was 2.6–5.7%, against 4.4%
     re-query noise. Results are in `real-agent-eval/v5/harm_attribution/stability/`.
10. **A local-checker arm was drafted and removed before the freeze** (§2.5), after an exploratory
    re-decision of v5 showed that a binary checker loses the correct REFUTED answers.
11. **The alias file was built after v5** (from Wikidata, blind to outcomes). Its grader is secondary,
    and the primary grader is unchanged.
12. **Same machine and the same single seed as v5.** v6 adds pool diversity, not seed or hardware
   diversity. Seeds are not varied, so that the pool remains the only manipulated factor.

## 14. Pre-written readings

**F1 (VV/VDF).**

| outcome | headline |
|---|---|
| H1a-VDF and H3a-VDF both reject | Verified default first beats majority and shows harm below 5% on a new, family-disjoint pool. This is its first confirmatory test; the rule was designed post hoc on v5. |
| H1a-VDF rejects, H3a-VDF fails | VDF's gains are confirmed; harm below 5% is not shown. Report H4 (c ≤ F against MAJ) and the remaining unverified-default harms. |
| H1a-VDF null or worse | The sequence stops. The post-hoc VDF gain does not carry to a new pool. |
| F1 holds on all of P but not without the design set | Reported as dependent on the items that informed the rule. |

**F2 (replication of v5).**

| outcome | headline |
|---|---|
| H1a-rep rejects and H3a-rep holds | v5's BE-G result replicates, now with harm below 5% shown. |
| H1a-rep rejects, H3a-rep fails, H3a-pool holds | Gains replicate. BE-G harm is below 5% across both pools pooled (secondary), but not shown in either pool alone. |
| H1a-rep rejects, H3a-rep and H3a-pool fail | Gains replicate. Harm equals checker false supports, as the bound predicts (H4). |
| H1a-rep null or worse | The v5 gain is pool-specific. Report the cross-pool table (§2.4). |

**Futility stop at 300 (VV/VDF b − c ≤ 0).** Reported as stopped, with the 300-item counts. No F1,
F2 or secondary test is run.

## 15. Pre-freeze checklist

1. Author approves item reuse (§6), including for VDF despite the selector study's fresh-items
   caveat. Author also approves the F1/F2 structure (§2), the pool (§4.1) and the budget (§8.8).
2. Models pulled. `[[POOL: …]]` slots filled. `pool_manifest.json` written.
3. Wrappers (§11) written and tested. `--synthetic-test` passes through `evaluate_v6.py`.
   `vdf_v6.py` passes the §5.2 reproduction gate on v5 data, and its report is hashed.
   The G-AK+A grader passes the gold-consistency check on all 1,100 items.
   `collect_v6.py --split dev` refuses a `--out` under `v5/`.
4. Qualification run (§4.3) done. `qualification_v6.json` and BEST recorded.
5. The v5 evidence cache and CB-S store cloned into `v6/results/conf/`, and their file counts recorded.
6. `FREEZE.json` written: v5's 56 entries, the §12.1 additions, the §12.2 files and this file.
   `pending` is emptied and the status set to frozen; then commit.

## 16. Amendments

None yet.
