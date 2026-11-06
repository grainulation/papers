# Eval v4 Stage A (dev): collection report

Stage A (dev, 160 items) is collected. On dev the preregistration (§7 step 3) allows only the
quantities below. No method accuracy, no b−c, and no H1/H2 contrast was written or looked at.
`evaluate_v4.py` ran its full code path blind: the Rust I/O went to a temporary directory, which
was then deleted.

## Freeze and environment

- **FREEZE.json.** All 6 hashes were verified before starting, and again by both scripts at run
  time. All matched.
- **Models.** All 5 digests equal `v3/results/run_manifest.json`:

  | model | digest prefix |
  |---|---|
  | llama3.2:3b | a80c4f17acd5 |
  | mistral | 6577803aa9a0 |
  | gemma2:2b | 8ccf136fdd52 |
  | phi3:mini | 4f2222927938 |
  | qwen2.5:3b | 357c53fb659c |

  Digests were read from `/api/tags`, because `/api/show` on this build has no digest field.
- **Server.**
  - Ollama 0.17.7, with `OLLAMA_NUM_PARALLEL=1` and `OLLAMA_MAX_LOADED_MODELS=0` (auto).
  - KV cache q8_0 and flash attention on, as in v3's log line.
- **Collection.**
  - Seeds: dispatch seed 20261101, request seed 42.
  - 160/160 items collected in 1,787 s.
  - 0 request errors and 0 retries.
- **Binary.** reducer sha256 `43c55b36…2981`, built from git 9e27f29 with a clean crate directory
  (`results/build_provenance.json`).
- **Pipeline test.** Run on 5 dev items in scratch, one per source plus a second PopQA:
  - collection worked;
  - parsing worked;
  - the blind evaluation ran;
  - the Python mirror matched the binary on every slot.

  The unblinded writers (paired_decisions, margins, H1/H2, S1–S8) were also exercised on
  synthetic raw records only. The statistics self-test passed.

## Parse audit and per-model rates (S6)

| agent | unparseable | rate | no ANSWER line | dev accuracy (all items) |
|---|---|---|---|---|
| llama3.2_3b | 36 | 22.5% | 33 | 0.506 |
| mistral | 14 | 8.8% | 14 | 0.550 |
| gemma2_2b | 9 | 5.6% | 0 | 0.463 |
| phi3_mini | 28 | 17.5% | 15 | 0.513 |
| qwen2.5_3b | 4 | 2.5% | 2 | 0.613 |

- **Where the failures are.** llama misses mainly on PopQA (17) and FEVER (10). phi3 misses
  mainly on FEVER (14); 2 of its responses hit the 1,024-token limit.
- **No agent exceeds the 50% threshold of §8,** so no ANSWER-line amendment is triggered.
- **M11 model** (highest dev accuracy, chosen per §7 step 3.5): **qwen2.5_3b**.
- **Per-answer details.** They are in `results/dev/parse_audit_v4.csv` and
  `responses_v4.jsonl`. These two files contain the G-AK verdicts, so the person labelling PopQA
  should use only `popqa_label_sheet.csv`.

## Yield and discordance (§7 step 3.4)

| quantity | value |
|---|---|
| eligible items (≥ 2 parseable answers) | 160 / 160 (no exclusions) |
| decisive conflicts | 80 |
| decisive conflicts by source | TQA 25, PopQA 8, FEVER 30, SciFact 17 |
| **yield y_A** | **0.50** |
| b+c, M1 vs M2 (prereg §7 wording) | 27 → ψ_A = 0.3375 |
| b+c, M3 vs M2 (H1 pair) | 26 → ψ = 0.325 |
| objects whose members grade differently | 0 |

## Implied item count (§7 step 4)

| pair | ψ\* | N\* (exact `min_n_stable`) | I = 4·⌈N\*/(4·y)⌉ | N\* from next Table 1 column (ψ = 0.35) | I | clamped I |
|---|---|---|---|---|---|---|
| M1 vs M2 | 0.3375 | 279 | 560 | 289 | 580 | **600** |
| M3 vs M2 | 0.325 | 269 | 540 | 289 | 580 | **600** |

Every reading gives **I = 600**: the first 600 items of `items_confirmatory.jsonl` in `order`.
The clamp's lower bound binds, so the choice of pair does not change the decision.

## Deviations and interpretations (for the §13 amendment)

1. **The ψ pair.** §7 step 3.4 and §11.2.8 still name M1 vs M2, while H1 is M3 vs M2
   (resolution 1). Both pairs were computed; both give I = 600.
2. **N\* for a ψ\* that is not a Table 1 column.** It is computed exactly with the function that
   produced Table 1. The next tabulated column gives the same I.
3. **The machine was not quiet** (§7 step 1). Other concurrent jobs ran `rustc` and the reducer during
   collection. The 1-minute load average ranged 2.3–11.0, median 4.8
   (`results/dev_load_log.txt`). No evaluator ran during collection.
4. **Digest check.** Digests were verified via `/api/tags`, not `/api/show`, which has no digest
   field in Ollama 0.17.7.
5. **Further analysis-code interpretations.** These cover answer-contribution confidence,
   ANSWER-line stripping before extraction, object-level grading for M2/M7, the dropped v3 tcp
   value groups, the S1 table scope and the H2 non-inferiority test. They are listed in
   `README.md`.

## Still open before Stage B

- **PopQA hand-check.** The author hand-checks the PopQA entity grading on at least 120 answer
  lines, using `results/dev/popqa_label_sheet.csv` (169 lines).
- **Possible grader revision.** If agreement with G-AK is below 0.90, `answer_key.py` may be
  revised once, using dev evidence only. Its new hash then needs freezing, and Stage A must be
  re-graded. This can change y_A and ψ.
- **Analysis team.** The analysis team adds the hashes in `CODE_FREEZE_PROPOSAL.json` to
  `FREEZE.json`, by amendment.
- **Stage B command.** `python3 collect_v4.py --split conf --n-items 600`, then a single
  `evaluate_v4.py --split conf --m11-model qwen2.5_3b`.
