# Eval v5 design: grounded agents, evidence-verified arbitration

Status: design only. Nothing here has been run except the Stage A analyses in §6.1. Those used dev
data only and can be reproduced from `real-agent-eval/v4/results/dev/responses_v4.jsonl`. Date
2026-10-22. The new evaluation is **eval v5** (`real-agent-eval/v5/`); the paper revision lives in
`v3/`.

## 0. Why a new study

Eval v4 tests whether a deterministic reducer beats majority vote when agents answer from memory.
That setup cannot test the mechanism overturn was built for, because closed-book small models give a
verifier almost nothing to check:

- half of the 332 cited identifiers do not resolve (the paper);
- only 340 of 709 parsed v4 dev answers (48%) carry any evidence item, and most of those are
  in-sentence markers rather than identifiers.

Majority vote ignores evidence by construction. Evidence should matter in one regime: **most agents
share an error, and a minority can show a passage that settles it.** v5 builds that regime
reproducibly. Every agent retrieves from one fixed, hashed corpus and may cite only passages it was
shown. Citations therefore always resolve, the checker sees the real evidence, and the reducer's
evidence term carries signal.

## 1. Claim and hypotheses

**Claim.** When agents must cite passages from a fixed corpus, sealing a validated per-passage
support check and arbitrating deterministically over it overturns wrong majorities more often than
right ones. It therefore beats majority vote and matches an LLM judge given the same evidence, and,
unlike the judge, every decision replays bit for bit and traces to one labelled passage.

**Unit.** A decisive conflict, defined as in v4 and method-blind: an eligible item (at least 2
parseable answers) with at least one correct and one incorrect answer under the mechanical grader
G-AK.

**Win condition (net gain).** On decisive conflicts, count:

- b: Overturn+E right and majority wrong (a wrong majority overturned);
- c: Overturn+E wrong and majority right (a right majority overturned).

The net gain is (b − c)/N. Also reported: the overturn rates p_w = b/#(majority wrong) and
q_r = c/#(majority right). Overturning wrong majorities counts only net of overturning right ones.

**Hypotheses.**

- **H1 (primary).** On decisive conflicts, the evidence-verified order-free reducer (BE, §5) is
  correct more often than canonical majority vote (MAJ).
  - Test: exact two-sided McNemar on (b, c), α = 0.05.
  - Reported with: the Newcombe 95% CI for (b − c)/N, an item bootstrap (10,000 resamples, seed 42),
    and p̂_w and q̂_r with Wilson CIs.
- **H2 (key secondary, own α).** BE is non-inferior to the LLM judge J.
  - Margin −0.05, one-sided α = 0.025, Newcombe CI.
  - Superiority is tested at 0.05 only if non-inferiority holds.
- **H3 (descriptive).** For BE versus J: calls, tokens, dollars and wall time per item; BE replay
  identity (checked on every item); J regeneration agreement (200-item re-run).

**What each outcome means.**

| outcome | reading |
|---|---|
| H1 null, p̂_w and q̂_r both high | The checker finds the truth, but checker errors also flip right majorities. The bottleneck is checker precision, not the boundary. |
| H1 null, p̂_w ≈ 0 | Minorities lacked checkable support, or support did not reach the score. The evidence-availability split (§6.2) tells which. |
| H1 positive, H2 fails | Sealed arbitration has an accuracy price relative to a holistic judge; we report it. |
| H1 positive, H2 holds | The target result. |

With v4 as the closed-book control, either outcome answers one question: does evidence-weighted
arbitration need checkable evidence to beat voting?

## 2. Corpus and retrieval

### 2.1 Machine constraints (measured)

- **RAM.** M3 Pro, `hw.memsize` 38,654,705,664 bytes (36 GiB).
- **Disk.** **7.3 GiB free on the data volume, and this binds.**
- **Models.** `~/.ollama/models` holds 12 GB, including `nomic-embed-text` (274 MB).
- **Missing tooling.** No Java, so no Pyserini or Lucene without a JDK. No scipy or bm25s yet.

### 2.2 Candidates

| corpus | content | download (HEAD) | licence | local cost | fit |
|---|---|---|---|---|---|
| FEVER 2017 wiki-pages | 5.4M Wikipedia lead sections, sentence ids | 1.71 GB zip | CC BY-SA 3.0 (accepted for v4, Q6) | stream from the zip. Store + BM25 index ≈ 8–10 GB. Index RAM ≈ 9 GB eager, < 1 GB with mmap (bm25s reports 4.4 → 0.5 GB on 2.7M-document NQ) | FEVER gold is defined on this dump. Most PopQA facts are in leads. TruthfulQA is partly covered. |
| BEIR FEVER | same leads, no sentence split | 1.24 GB | CC BY-SA | same | worse for spans |
| KILT knowledge source | 5.9M full articles (2019) | 37.3 GB | CC BY-SA | ≥ 80 GB disk | best TruthfulQA coverage, but infeasible here |
| SciFact corpus | 5,183 abstracts | 8.3 MB, already local | ODC-By 1.0 | trivial, and dense retrieval is feasible | the SciFact open setting |
| DPR psgs_w100 | 21M passages (2018) | ≈ 13 GB | CC BY-SA | ≥ 40 GB | no gain over FEVER |

**Recommendation: two corpora, routed by item source.** Source is gold-blind metadata, so routing on
it is fair.

- **SciFact items** retrieve from the SciFact corpus.
- **All other items** retrieve from the FEVER 2017 dump.
- **Passages** are ≤ 1,000-char chunks of a lead, cut on sentence boundaries and keyed
  `fever17:<page_id>:<chunk>`.
- **Disk.** This needs about 15 GB free (gate G1).

**Fallback without disk: SciFact only.** That is 283 fresh items at yield ≈ 0.42, or about 120
decisive conflicts. It is powered only for Δ ≥ 0.15 (N = 129 at ψ = 0.35, `power/POWER.md` Table 1).

**TruthfulQA coverage risk.** 475 of 790 TruthfulQA questions cite Wikipedia, but the dump holds only
lead sections. Dev measures evidence availability per source (§6.2). If TruthfulQA is below 30%, its
quota moves to PopQA and FEVER. We never add TruthfulQA source pages to the corpus: a corpus built
from gold sources leaks gold.

### 2.3 Retrieval

- **Library and settings.** BM25 via `bm25s` (pure Python, numpy and scipy, versions pinned).
  - Tokenizer: lowercase, regex split, built-in English stopwords.
  - **No stemmer**, which avoids the PyStemmer C extension.
  - k1 = 1.2, b = 0.75.
- **Why not dense retrieval.** Over 5.4M passages it needs about 16 GB of vectors and hours of
  embedding. Dense is used only on SciFact (§3.2).
- **Deterministic top-k.**
  1. Take the top 50.
  2. Quantize: `score_q = round(1000·score)`.
  3. Sort by (−score_q, passage_key) and keep the top k.
- **Index identity.** `index_sha256` hashes:
  - the index files;
  - the tokenizer config and pinned versions;
  - `corpus_sha256`, which itself covers the corpus file and the chunker version.
- **Retrieval records.** Every query is sealed as
  `bran-retrieval/1 = {query, corpus_id, index_sha256, k, results: [{passage_key, score_q}]}`. The
  hash goes into the run manifest. The reducer never reads it.
- **Tests.**
  - The same query gives the same record.
  - A rebuilt index gives the same hash and the same results on 1,000 fixed queries.
  - mmap and eager loading give the same results.

### 2.4 Local corpus capture: minimal deltas to `v2/evidence-verification-spec.md`

1. **New identifier kind `corpus`.** Added in Rust (`overturn/src/evidence.rs:36` `IdentifierKind`) and
   Python (`tools/evidence/canonical.py`, `capture.py`).
2. **Record fields for a passage.**

   | field | value |
   |---|---|
   | `requested`, `request_url`, `resolved_url`, `canonical_url` | `corpus://<corpus_id>/<passage_key>` |
   | `redirects` | `[]` |
   | `http_status` | `null` |
   | `content_type` | `text/plain` |
   | `content_sha256` | hash of the passage's UTF-8 bytes |
   | `extraction.method` | `corpus/1` |
   | `robots` | `{checked: false, allowed: null, robots_sha256: null}` |
   | `license_note` | from the corpus manifest |
   | outcome | `ok`, or `ok_no_text` if the passage is under 200 chars |

3. **Corpus pinning.** `capture_tool_version` includes `corpus_sha256`, so a new corpus means new
   capture ids.
4. **No fabrication outcome is needed.** Citations are schema-constrained to the agent's own P1–P5
   (§3.3). Any impossible id is recorded as `invalid_identifier` (dead), using the existing enum.
5. **Cross-reference key.** `corpus:<passage_key>`, via the existing `canonical_url` rule. Distinct
   agents citing one passage labelled `supports` earn the xref bonus.
6. **Policy change: `unchecked_factor` = 0.5.** Under the default 1.0, an `ok` capture whose check
   was refused scores 0.85·0.75·1.0 = 0.638, the same as a supported passage. Hosted-checker
   refusals (1.3% of the SciFact slice) would then count as support. Spec open question 1 lists this
   alternative.

Nothing else changes in the record, the store, `bran-artifact/3` or replay. Regressions to keep
green:

- all `/2` and `/3` replay dumps;
- spec §4 tamper tests 1–6, re-run on corpus captures;
- legacy policy hashes, unchanged.

## 3. Agent protocol

### 3.1 Turns

Everything is as in v4 except the turns below: the same five models and digests, temperature 0.7,
seed 42, dispatch seed 20261101, and `OLLAMA_NUM_PARALLEL=1`.

1. **Query turn.** "Write one search query (≤ 12 words) for evidence that answers this question."
   - The agent sees the question. For multiple-choice items it does **not** see the options, which
     would steer every query toward the same distractor wording.
   - `num_predict` 32.
2. **Retrieve.** BM25 top-k = 5 for that agent's own query, labelled P1–P5 by rank.
3. **Answer turn.** The agent gets the question, the options and its five passages.
   - It must cite only P-labels that support its answer.
   - If no passage helps it still answers, citing nothing. That keeps memory-driven majorities, the
     target regime, in play.

### 3.2 Keeping conflicts

- **Sources of diversity.** Each agent's own query gives it its own top-5; no item-keyed shared
  retrieval is used. Temperature 0.7 adds more.
- **SciFact retriever split.** Agents alternate between BM25 and dense `nomic-embed-text` retrieval,
  assigned by a seeded per-item rule balanced across models. With 5k abstracts this is cheap, and the
  embeddings are sealed by hash.
- **Pre-declared fallback arm (mixed fleet).** It is used only if the dev gate (§6.2) fails on yield
  or majority-wrong share.
  - On each item, 2 of 5 agents answer closed-book, chosen by `Random("v5-cb:"+id)` and balanced so
    each model is closed-book on 40% of items.
  - Its asymmetric evidence favours BE, and the paper must say so.

### 3.3 Answer format

v4's ANSWER line failed to parse in 2.5–22.5% of responses: llama 22.5% and phi3 17.5%, mostly a
missing line plus two runs at the token limit. v5 uses Ollama structured outputs, `format` = a JSON
schema (supported since Ollama 0.5; confirm on 0.17.7 in the W2 pilot):

```json
{"type":"object","required":["reasoning","answer","citations","confidence"],
 "properties":{"reasoning":{"type":"string","maxLength":600},
  "answer":{"enum":["A","B","C","D"]},
  "citations":{"type":"array","maxItems":3,"items":{"enum":["P1","P2","P3","P4","P5"]}},
  "confidence":{"enum":["high","medium","low"]}}}
```

- **`answer` field.** Enumerates the item's actual options, or `["SUPPORTED","REFUTED"]`, or a
  string of at most 60 characters for PopQA.
- **Field order.** `reasoning` comes first, so the model reasons before committing.
- **Length.** `num_predict` 512, with truncation counted.
- **Expected parse failure.** Near 0. The dev gate is < 5% per agent.

**Lowering.** One contribution per parsed answer:

- triple `(v5-<id>, answer, <canonical value>)`, AFFIRM, lowering HIGH;
- confidence taken from the field;
- one `CITATION` item per cited passage, weight 1.0, with `capture_ref` → corpus capture and
  `support_ref` → support record;
- no v3 marker extraction.

### 3.4 Support propositions

The checker labels (proposition, passage) pairs. It never sees the other answers or any vote count.
Propositions are rendered gold-blind:

| source | proposition for value v | label mapping |
|---|---|---|
| FEVER, SciFact | the item claim C | SUPPORTED takes the label as is; REFUTED takes it with supports and refutes swapped |
| TruthfulQA MC | "Q: <question> A: <option text of v>" | as is |
| PopQA | the PopQA relation template with subject and v ("The occupation of X is v") | as is |

For binary items, one (C, passage) check serves both sides. Checks are de-duplicated by
(proposition, passage_key).

**Checker.** The accepted `76d44ce2…`: Claude Sonnet 5.5 via `claude -p`, effort low, tools off.

- The checker work re-validates it once on FEVER, now that FEVER sentence text is local.
- Any prompt change gives a new `checker_id`, which must pass the SciFact validation again
  (Amendment 1a).

## 4. Benchmarks

| source | why majorities go wrong | v4 dev (§6.1) | licence | fresh pool | v5 primary |
|---|---|---|---|---|---|
| TruthfulQA MC1 | shared imitative falsehoods | majority wrong on 10.0 of 25 decisive (40%) | Apache-2.0 | 451 reserve + 100 uncollected v4 extension | 300 |
| SciFact, open retrieval (abstract **not** in the prompt) | affirmation bias | majority wrong on 10.5 of 17 (62%); on REFUTED gold, 8.5 of 11 (77%), even with the abstract in the prompt | CC BY 4.0 / ODC-By | 183 claims outside the benchmark **and** the checker's slice/pilot/injection sets, + 100 extension = 283 | 250 |
| PopQA, long tail | closed-book all-wrong; retrieval lets a minority find the fact | 3.1 of 8 (39%); 17 of 40 items all-wrong | MIT / CC0 | 924 reserve + 100 extension | 250 |
| FEVER | **control**: majority usually right, so this measures c | 4.5 of 30 (15%) | CC BY-SA 3.0 | 6,215 reserve + 100 extension | 200 |

- **Dev split.** The 160 v4 dev items, re-rendered without SciFact abstracts. This gives a paired
  closed-book versus grounded comparison, reported descriptively.
- **Confirmatory draw.** Seed 20261201, stratified as in v4: by source, by gold label within SciFact,
  and by popularity stratum within PopQA.
  - Items are never selected on model output. The regime is targeted through source choice only,
    and the paper says so ("benchmarks chosen to contain shared misconceptions").
- **Exclusions.**
  - All 600 v4 Stage B items, so v4 unblinding cannot inform the item choice.
  - The 220 SciFact claims used in checker validation, which would make checks circular.
- **Grading.** G-AK, unchanged, so no LLM is in the grading loop. Its known PopQA bias stands: 6 of
  169 false positives against the simulated annotators.

## 5. Methods

| id | method | role |
|---|---|---|
| MAJ | plurality over canonical answers, seeded-random ties (v4 M2) | H1 baseline |
| BEST | best single model on v5 dev, fixed before confirmatory | strong baseline |
| B0 | order-free reducer without the evidence policy (v4 M3) | isolates the evidence policy |
| **BE** | B0 + evidence policy (§2.4) + candidate mode selected on dev | **H1, H2** |
| EO | evidence-only weights (1,0,0,0,0) + evidence policy | do the other four features matter? |
| VV | verified vote: plurality among answers with ≥ 1 `supports` citation, else MAJ | simplest evidence-aware rule. If BE ≈ VV, the contribution is the boundary, not the weights. |
| J | LLM judge with the same evidence | H2, H3 |
| RS | RAG solver: the judge model with the question and the union of agents' passages, no agent answers | reference ceiling |
| ORC | oracle | bound |

### 5.1 BE configuration, selected on dev

The grid is {member, value:max, value:pooled} × NEI factor {0.5, 0.1}. We take the configuration
with the largest dev (b − c) against MAJ, break ties by the fewest changed fields, then freeze its
policy hash. Dev is never pooled with confirmatory data, and all 6 policy hashes are recorded.

The selection is needed because each mode has a plausible failure:

- **`value:pooled`.** Three wrong agents citing not-enough-information passages pool to
  min(1, 3 × 0.319) = 0.96, which beats one correct `supports` citation at 0.638.
- **Member mode.** It ignores headcount, so a single checker false positive can flip a right
  majority.

### 5.2 Judge J

- **Model.** The same `claude-sonnet-5-5` and `claude -p` pin as the checker, effort low, tools off.
  Using the same model on purpose means J and BE differ only in decision procedure, and the
  checker-model circularity cancels out of H2.
- **Input.** The question and options, then the five answers, each with the full text of its cited
  passages. Agent order is shuffled by `Random("v5-judge:"+id)`, and passages are marked untrusted
  with the checker's delimiters.
- **Output.** JSON, constrained to the proposed values. It is sealed and cached by prompt hash.
- **Drift.** The CLI has no seed, so drift is measured by a 200-item regeneration.
- **Cost.**
  - Input is about 4k tokens. Estimate: $0.005–0.01 per item, scaled from the measured $0.0010 per
    1.6k-char check.
  - About $6–12 for 1,200 calls.
  - Optional cost point: `claude-haiku-4-5` with the same prompt.

### 5.3 Why BE vs J is the comparison that matters

Beating MAJ shows only that evidence helps. The alternative a practitioner would actually deploy is
"give a strong model the evidence and let it decide". Against that alternative, sealed decomposed
arbitration differs in four ways:

- **Determinism.** BE replays from A with no model call. J is a fresh hosted generation; even the
  checker's labels drifted on 2 of 50 re-runs.
- **Audit.** Every BE overturn names the passage and label that caused it.
- **Bias exposure.** The checker never sees headcount; J sees five answers and can follow the
  majority.
- **Cost.** Checks are small and de-duplicated; J pays for one long context per item.

If BE ≥ J − 0.05, auditability costs no measurable accuracy. That turns the systems claim into an
empirical one.

## 6. Power

### 6.1 Stage A (v4 dev, closed-book)

Computed from `results/dev/responses_v4.jsonl` on majority only; no overturn selection was read. On ties,
majority correctness counts as the expectation of the seeded-random tie-break.

| quantity | all | TQA | PopQA | FEVER | SciFact |
|---|---|---|---|---|---|
| decisive conflicts | 80 | 25 | 8 | 30 | 17 |
| majority correct (expected) | 51.9 | 15.0 | 4.9 | 25.5 | 6.5 |
| **majority wrong, correct minority exists** | **28.1 (35.2%)** | 10.0 (40%) | 3.1 (39%) | 4.5 (15%) | 10.5 (62%) |
| majority strictly wrong (no tie) | 20 (25%) | 8 | 2 | 2 | 8 |
| ties at the top | 16 | 4 | 2 | 5 | 5 |
| ≥ 3 agents on one wrong value | 14 (17.5%) | 6 | 0 | 0 | 8 |
| items all agents wrong (out of reach) | 29 / 160 | 8 | 17 | 0 | 4 |

- **Who the correct minority is.** In 17 of the 20 strict majority-wrong items it is a single agent:
  qwen 10, phi3 6, mistral 2, llama 2, gemma 1.
- **Its evidence.** In 13 of the 20 it carried at least one evidence item.
- **Disclosure.** v4 prereg §7 allows only yield and ψ on dev. This majority accuracy was computed
  after the v4 code, items and stopping rule were frozen, on dev only, for this design. The
  analysis team should note it in the v4 record.

### 6.2 Calculation

**Model.** Let m = P(majority wrong | decisive). Then b/N = m·p_w and c/N = (1 − m)·q_r, so
Δ = b/N − c/N and ψ = b/N + c/N.

**Test and N.** Exact two-sided McNemar, α = 0.05. N is the smallest value at which power ≥ 0.80 and
stays there for 25 further values of N. The code reproduces v4 Table 1 (207 at ψ = 0.25, Δ = 0.10).

| m | p_w | q_r = 0.05 | q_r = 0.10 | q_r = 0.15 |
|---|---|---|---|---|
| 0.35 | 0.3 | 221 | 872 | — |
| 0.35 | 0.4 | 123 | **302** | 1,070 |
| 0.35 | 0.5 | 83 | 165 | 374 |
| 0.25 | 0.4 | 293 | > 1,500 | — |
| 0.25 | 0.5 | 179 | 658 | — |

"—" marks Δ ≤ 0.02, which is unreachable.

**Reading.** Power depends far more on q_r than on p_w. Protecting right majorities is the real
design problem, which is why we run the §5.1 grid and include FEVER.

**Planning.**

- Point: m = 0.35 (Stage A), p_w = 0.4, q_r = 0.10, giving Δ = 0.075, ψ ≈ 0.21 and N = 302.
- Stopping rule: Δ fixed at 0.075 and ψ floored at 0.25 give **N\* = 368**. For comparison, N\* = 294
  at ψ = 0.20 and 438 at 0.30.
- Yield: v4 was 0.50. Planning assumes 0.45, because retrieval converts PopQA all-wrong items into
  decisive ones but may make some FEVER items all-right. That implies about 820 items.
- **Plan: 1,000 primary items.**

**Stopping rule (v4 discipline: b + c only, never b − c).**

- I = ⌈N\*(ψ_dev)/y_dev⌉, clamped to [1,000, 1,400].
- ψ_dev = (b + c)/N for BE vs MAJ on dev, floored at 0.25.
- Any extension draws on TQA, PopQA and FEVER; the SciFact pool is exhausted.
- There are no interim looks.

**Pre-declared dev gate.** All four must hold to proceed as planned:

| check | threshold | if it fails |
|---|---|---|
| yield y_dev | ≥ 0.30 | mixed-fleet arm |
| majority-wrong share m_dev | ≥ 0.20 | mixed-fleet arm |
| evidence availability, per source | ≥ 30% | the §2.2 TQA switch |
| parse failure, per agent | < 5% | one schema fix |

Evidence availability is the share of decisive items where some agent's shown top-5 contains a
passage labelled `supports` for the gold value. It is a diagnostic only, never a selector.

**H2 power.** Normal approximation, true difference 0, margin −0.05:

| N | ψ(BE, J) = 0.15 | ψ(BE, J) = 0.10 |
|---|---|---|
| 368 | 0.70 | 0.86 |
| 450 | 0.78 | 0.92 |

This is adequate only if BE and J mostly agree. It is reported as a limitation; the study is not
resized for it.

## 7. Threats and risks

1. **Retrieval makes everyone agree.**
   - Mitigations: agent-issued queries, options hidden during the query turn, the dev gate, and the
     mixed-fleet arm.
   - Prior evidence that the regime survives grounding: v4 SciFact had the abstract *in the prompt*,
     yet the majority was wrong on 62% of decisive conflicts (77% on REFUTED). Reading errors
     persist when evidence is present.
2. **The checker is the real decision-maker.** By design, yes: only an accurate verifier can overturn
   a confident majority. Overturn contributes three things:
   - model judgment enters only as atomic, validated, sealed (proposition, passage) labels that never
     see headcount;
   - the decision is a replayable function of those labels;
   - the policy, not the model, sets how labels combine with confidence and agreement.

   Three comparisons test whether this matters:

   | comparison | what it tests |
   |---|---|
   | BE vs J (same model, same evidence) | the architecture |
   | BE vs RS | whether the small agents add anything over the checker model alone |
   | BE vs VV | whether overturn's scoring beats a one-line rule |

   If RS beats BE, the paper says arbitration buys auditability, not accuracy.
3. **Circularity with the checker model.**
   - J, RS and the checker deliberately share Sonnet 5.5, and grading is mechanical.
   - Validation claims are excluded from the items: the 220 SciFact claims, and the FEVER validation
     slice, which is drawn outside the item draw.
   - Sonnet's possible training exposure to FEVER, SciFact and TruthfulQA inflates BE, J and RS
     together, so it biases H1 more than H2. Reported.
4. **Corpus leakage.**
   - The corpora are general dumps, built independently of the items. Gold passages exist in them as
     in any open-retrieval benchmark.
   - Forbidden: adding TruthfulQA source pages, or filtering the corpus by gold.
   - FEVER's labels are defined on this same dump. PopQA facts newer than 2017 count against
     retrieval and are reported by stratum.
5. **Checker false `supports` on wrong answers drives q_r.**
   - SciFact `supports` precision is 0.923.
   - Mitigations: the FEVER validation and the NEI factor chosen on dev.
   - q̂_r is reported per source.
6. **Checker refusals and parse errors** score at `unchecked_factor` 0.5. Their rate is reported.
7. **Injection.** The corpus is fixed Wikipedia and abstracts, not pages an attacker chose. The
   delimiters and neutralizer are kept anyway.
8. **v4 unblinding contaminates design choices.** This document fixes the grid, methods and items
   first. Freeze the v5 prereg before anyone reads v4 confirmatory accuracy, or record the order.
9. **Time and cost on this machine.**

| step | basis | estimate |
|---|---|---|
| download + BM25 build | 1.7 GB streamed, 5.4M leads | ≈ 1 h, peak RAM ≈ 18 GB (Ollama idle) |
| per item | v4 measured 11.2 s (dev, 1,787 s/160) and 10.5 s (Stage B, 4,482 s/427). Add 5 query turns (≈ 3 s) and about 1k more prompt tokens per agent, serialized (≈ 8–13 s); output capped at 512 tokens instead of 1,024 | **≈ 25 s** (15–30); a 20-item timing pilot confirms |
| dev 160 + pilot 20 | | ≈ 1.3 h |
| confirmatory 1,000 (max 1,400) | | ≈ 7 h (max 9.7 h) |
| support checks | ≈ 8 de-duplicated checks per item × 1,180 items, at $0.0010 and 3 s, 6 workers | ≈ 1.3 h, ≈ $10 |
| FEVER checker validation | 350 calls | ≈ 10 min, < $1 |
| J + regeneration + RS | ≈ 2,400 calls | ≈ 0.7 h, $15–25 |
| reducer, replay, S10 | ms per item | < 10 min |
| **total** | | **≈ 11–12 h machine time (≈ 14 h at maximum extension), ≈ $30–40** |

v4 Stage B has about 30 minutes left (427/600 at 4,482 s). No v5 Ollama work starts until it finishes
and its raw files are sealed.

## 8. Work packages

| work package | owns | depends on | hands off |
|---|---|---|---|
| preregistration | `real-agent-eval/v5/PREREGISTRATION.md`, `v5/FREEZE.json`, this file | all | frozen prereg (hashes of items, corpus manifest, index, schema, code, binary, policies) |
| corpus | `tools/corpus/` (`build.py`, `retrieve.py`, `manifest.json`, tests); git-ignored `corpus-cache/` | G1, G2 | `corpus_manifest.json`; `retrieve()` returning `bran-retrieval/1`; determinism tests |
| corpus capture | `tools/evidence/corpus_capture.py` + tests; `v3/evidence-corpus-addendum.md`; `IdentifierKind::Corpus` hunk + tests in `overturn/src/evidence.rs` | corpus passage format | corpus captures; `/3` round-trip and tamper tests green; legacy hashes unchanged |
| harness | `real-agent-eval/v5/collect_v5.py`, `v5/prompts/`, `v5/schema/` | corpus; v4 Stage B done | raw records (query, retrieval, JSON answer, arrival); parse audit; timing pilot |
| items | `real-agent-eval/v5/benchmark/` | — | frozen items plus exclusion proofs |
| checker | `tools/evidence/support/propositions.py`; FEVER slice and report in `support/validation/` | corpus | proposition renderer and label mapping; FEVER validation bound to `checker_id` |
| judge | `tools/judge/` | harness | sealed J and RS outputs; cost and drift report |
| evaluation | `real-agent-eval/v5/evaluate_v5.py`, `v5/power/`, `v5/make_results.py` | corpus capture, harness, checker, judge | dev gate table and BE grid; then `RESULTS.md` (H1–H3) |
| paper | the paper (not part of this artifact) | evaluation, v4 results | the revised paper (§9) |

**Waves.**

- **W1 (no Ollama; can start now).** corpus build, item draw, corpus-capture addendum and Rust hunk, proposition renderer,
  power script and an evaluator on synthetic records.
- **W2 (after v4 Stage B).** In order:
  1. harness timing pilot;
  2. dev run;
  3. checker FEVER validation and dev checks;
  4. dev judge;
  5. gate table and grid.
- **G4.**
- **W3.** Freeze, then confirmatory collection on a quiet machine, then checks and judge.
- **W4.** The evaluation runs once, then the paper is revised.

**Author gates (plain language).**

- **G1 (disk).** "The Wikipedia corpus needs about 15 GB free; the disk has 7 GB. Free space, allow an
  external drive, or run the smaller SciFact-only study?"
- **G2 (downloads).** "OK to download the 1.7 GB FEVER Wikipedia file (CC BY-SA, as in v4) and install
  bm25s and scipy?"
- **G3 (spend).** "OK to spend about $30–40 of Claude usage on passage checks and the judge baseline?"
- **G4 (go/no-go after dev).** "On dev, X% of disagreements had the majority wrong, and Y% of items
  still had a real disagreement. Proceed, or switch to the pre-declared setup where two agents per
  item answer without retrieval?"
- **G5 (paper shape).** "One paper with a systems half and a grounded-evaluation half (recommended),
  or v4 now and v5 as a separate paper?"

## 9. What carries over and how the halves fit

**Systems half (unchanged).** v2 §§3–6, §7.1–7.2 and Appendices B–D and F, namely:

- the sealed boundary, content-addressed ids and the certificate;
- replay across 4 builds and 2 ISAs, and 36 of 36 tamper cases on `bran-artifact/4`;
- millisecond reduction against tens of seconds of generation;
- the Lean results (deadband homogeneity, default-weights impossibility, polytope robustness);
- the capture and support design and checker validation (Table 7);
- the two evaluation pitfalls: recency voting through Schulze, and polarity-blind grading.

**Evaluation half: one variable, whether arbitration has checkable evidence.**

1. **Closed-book (v4, preregistered).** Citations mostly do not resolve, and H1/H4 are reported as they
   fall. The expected reading: without checkable evidence, deterministic arbitration is at best
   non-inferior to voting, and it cannot overturn a shared misconception.
2. **Grounded (v5, preregistered).** Evidence always resolves.
   - H1: net overturning of wrong majorities.
   - H2: what replayability costs in accuracy against a judge given the same evidence.
   - H3: cost and drift.
3. **Linking analysis (descriptive), on the 160 shared dev items.** Closed-book versus grounded yield,
   m and evidence attachment (48% of answers closed-book, against ≈ 100% of citing answers
   grounded).

**How the halves connect.**

- Score separation, the precondition of Proposition 2, held in 0 of 29 free-text conflicts. v5
  re-measures it (S4). A supports-versus-NEI gap of 0.32 per citation (Table 1) makes separation
  reachable, so the paper can report how often the Lean precondition holds once evidence carries
  signal.
- The replay guarantee is what makes BE versus J meaningful: equal accuracy *at full replayability*
  is the result.

**Contribution list.** Findings 1–3 and 5 stay. Finding 4 becomes: "closed-book, arbitration does not
beat majority vote; grounded, it [overturns wrong majorities at net gain Δ, CI] and [is / is not]
non-inferior to an LLM judge given the same evidence".
