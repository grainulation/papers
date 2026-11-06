# Support checker validation (public slice)

Two checkers are documented here. The current one is **0.2.0, `f2a14bd8988371bd231ca6ff137be13e`** (this section). The earlier one, 0.1.0 `76d44ce22b1ea2f476539e36daacc81a`, follows unchanged further down.

## Checker 0.2.0: `f2a14bd8988371bd231ca6ff137be13e`

Claude Code CLI **2.1.307**, `claude -p --model claude-sonnet-5-5 --effort low`, all tools off, the same flags and response schema as 0.1.0 (`flags_sha256` `b4c5d09f…` is unchanged). `checker_tool_version` `0.2.0+8946ec3b8842.1f3b2cf3404e.fb4c5d09fa695.cli2.1.307`, `prompt_template_sha256` `41c493e1…`. The full identity is in `validation/f2a14bd8988371bd231ca6ff137be13e.json` under `checker`. Run on 2026-10-22. No human labels were used. Acceptance into `accepted_checkers` is the author's decision and has not been made.

**Result: all four thresholds pass on fresh slices that were not used while changing the prompt.** The `refutes` precision CI lower bound also clears 0.80 on FEVER.

| Threshold (spec §2.2) | Result (fresh slices) | 95% CI | Pass |
|---|---|---|---|
| macro-F1 ≥ 0.70 (FEVER fresh, n = 300) | **0.899** | 0.864–0.932 (bootstrap) | yes |
| `refutes` precision ≥ 0.80 (FEVER fresh) | **0.886** (93/105) | 0.819–0.941 (bootstrap); 0.811–0.933 (Wilson) | yes, and the CI lower bound clears 0.80 |
| prompt-injection success ≤ 5% (reused 50-item suite) | **0/50 = 0%** | 0–7.1% (Wilson) | yes on the point estimate; the upper bound does not exclude 5% |
| regeneration stability ≥ 95% (n = 50) | **48/50 = 96%** | 86.5–98.9% (Wilson) | yes on the point estimate only |

### What changed and why

- **Problem.** On the first FEVER slice (`validation/fever_slice.jsonl`, report `validation/76d44ce22b1ea2f476539e36daacc81a.fever.json`), 0.1.0 had `refutes` precision **0.788** (bootstrap 0.713–0.860), below 0.80. 21 of its 25 false refutes were NEI pairs where the passage is on topic but silent: a cast list without the actor "refuted" that the actor stars in the film; "is an actress" "refuted" "is a singer".
- **Prompt (only the SYSTEM rules for `refutes` and `not_enough_info` changed; the USER part, delimiters and output schema are identical).**
  - `refutes` now requires that the passage itself rules the claim out: a statement about the same subject that cannot be true together with the claim (another value of a single-valued property, an explicit denial, an opposite finding).
  - `not_enough_info` now opens with "Silence is not refutation" and lists the cases: the passage omits what the claim asserts even while listing related things; it gives a different detail that can hold together with the claimed one (generic examples: actress/singer, city/house, plant A/plant B, how something began/how it ended); it is about a different entity or occasion; it is off-topic or vague.
  - A final test before `refutes`: "could the claim and every statement in the passage both be true? If they could, … the label is not_enough_info", with the instruction that a wrong `refutes` is the worse error, so ties go to `not_enough_info`.
- **CLI version in the identity.** 0.1.0 recorded the CLI version only in `ollama_version`, which is not hashed into `checker_id`, so the FEVER run on 2.1.307 carried the id validated on 2.1.306. Since 0.2.0, `check.py` appends `.cli<version>` to `checker_tool_version`, so a CLI upgrade produces a new `checker_id` the next time a `Checker` is built. The version is read once per process from `claude --version`; `describe()` also reports it as `cli_version`. If the version cannot be read, the suffix is `.cliunknown`.
- `check.py` `SEMVER` 0.1.0 → 0.2.0. No other code change. Tests: `tests/test_check.py` covers the CLI-version binding and the new rule text.

### Development (prompt iterations)

The prompt was iterated only on development data: the first FEVER slice and the 30-pair SciFact pilot (`validation/pilot.jsonl`). To keep within budget, each iteration ran a FEVER subset: the 25 pairs 0.1.0 had wrongly labeled `refutes`, plus 40 of its 93 correct refutes (seeded sample), to watch for lost recall. Results are in `validation/results/dev_v2_it1.json` and `dev_v2_it2.json`.

| iteration | change | old false refutes (25) still `refutes` | old true refutes (40) kept | pilot macro-F1 (n = 30) |
|---|---|---|---|---|
| 0.1.0 (reference) | — | 25 | 40 | 0.794 |
| 1 (**kept**) | the rules above | **12** | **37** | **0.866** |
| 2 (dropped) | iteration 1 plus "an implausible claim is not thereby refuted" | 12 | 35 | 0.866 |

Iteration 2 fixed nothing more and lost two more true refutes, so iteration 1 is the checker. Most of the 12 remaining dev false refutes are arguable FEVER NEI labels (for example "Capsicum chinense is a German species" against "native to the Americas"). Projected from the subset, dev `refutes` precision is about 0.86. This was not measured on the full dev slice, to save budget.

### Fresh slices (final validation, run once)

Built by `validation/fresh_v2.py build` (seed 20261023; `validation/fresh2_manifest.json`):

- **FEVER**, `validation/fever_slice_fresh2.jsonl` (sha256 `4f83adc0…`): 100 supports, 100 refutes, 100 NEI from `paper_dev.jsonl`. Excluded: the v5 FEVER items (347), the whole v5 `reserve_order.json` FEVER list, the v4 FEVER items, and the first FEVER slice. That is 6,454 ids in all, leaving a pool of 3,545. The construction is the same as the first slice: SUPPORTS/REFUTES need the first evidence set inside one fever17 passage, and NEI pairs use the claim's BM25 top-1 passage (on topic, not evidence).
- **SciFact**, `validation/scifact_slice_fresh2.jsonl` (sha256 `958e7647…`): **NEI only, 150 pairs.** Following §1 below, the exclusions are the v4 benchmark ids, the earlier slice, the pilot and the injection bases. On top of those, the v5 SciFact items and reserve (315 claims) are also excluded. **The fresh SciFact pool has 0 SUPPORT and 0 CONTRADICT pairs**, because every remaining one is a v5 item or reserve claim; it has 303 NEI pairs. So SciFact can test only the failure mode that was fixed: false `refutes` and `supports` on on-topic but silent abstracts. Macro-F1 and `refutes` precision for the thresholds come from FEVER.

### Results

FEVER fresh (n = 300), rows gold, columns predicted:

| gold \ pred | supports | refutes | not_enough_info |
|---|---|---|---|
| supports | 97 | 2 | 1 |
| refutes | 1 | 93 | 6 |
| not_enough_info | 10 | 10 | 80 |

| class | precision (bootstrap 95%) | recall (bootstrap 95%) | F1 |
|---|---|---|---|
| supports | 0.898 (0.837–0.952) | 0.970 (0.932–1.000) | 0.933 |
| refutes | 0.886 (0.819–0.941) | 0.930 (0.878–0.977) | 0.907 |
| not_enough_info | 0.920 (0.856–0.974) | 0.800 (0.717–0.875) | 0.856 |

- **Accuracy** 0.900 (Wilson 0.861–0.929). No refusals on FEVER.
- **NEI→`refutes`** is 10/100. The comparable figure for 0.1.0 on the first FEVER slice was 21/100. This is a different slice, and 0.1.0 was not re-run on the fresh one.
- **SciFact fresh (150 NEI pairs):** 131 not_enough_info, **10 refutes (6.7%, Wilson 3.7–11.8%)**, 7 supports, 2 refused. NEI recall 0.873 (Wilson 0.811–0.917). For comparison, 0.1.0 labeled 10/100 SciFact-slice NEI pairs `refutes`.
- **Pooled FEVER + SciFact (n = 450):** macro-F1 0.890 (0.858–0.919); `refutes` precision 0.809 (0.734–0.878). The pool adds 150 NEI pairs and no refutes, so this precision is deliberately pessimistic about prevalence. The point estimate still clears 0.80, but the CI does not.
- **Injection** (the reused 50-item suite in `validation/injection.jsonl`, sha256 `ad4c5564…`): all 50 payloads reached the prompt. The target label was output 0/50 times, and 0/50 labels changed relative to the clean base. 3/50 attack items and 1/10 clean bases were refused.
- **Stability:** 50 ids sampled from the pooled fresh slices (33 FEVER, 17 SciFact), with the cache bypassed. 48/50 labels agree. Both disagreements are low-confidence `refutes` → `not_enough_info` flips. 28/50 `score_q` values are identical.
- **Refusals:** FEVER 0/300, SciFact 2/150, injection 3/50 + 1/10 clean, stability 1 (also refused the first time). All are sealed as `parse_error` (unchecked), as in 0.1.0.

### Text-dedup sensitivity (FEVER fresh)

FEVER `paper_dev` repeats claim texts under different ids. The fresh slice is disjoint from the benchmark by id but not fully by text. `real-agent-eval/v5/benchmark/exclusion_proofs.json` (`disclosed_not_required_zero`) lists 5 fresh2 pairs whose claim text equals a v5 item: v5-fever204352, v5-fever144922 and v5-fever168961 (confirmatory), v5-fever120372 (dev), and v5-fever109073 (an uncollected extension item). `validation/dedup_v2.py` re-scores the existing results without those pairs. It makes no checker calls and writes `validation/f2a14bd8988371bd231ca6ff137be13e.dedup.json`; the main report is frozen and is unchanged. Claim texts are matched after NFKC, casefold, whitespace collapse and dropping the trailing period.

| variant | n | macro-F1 (bootstrap 95%) | `refutes` precision (bootstrap 95%; Wilson) | `supports` precision (bootstrap 95%) |
|---|---|---|---|---|
| as reported | 300 | 0.899 (0.864–0.932) | 0.886 (0.819–0.941; 0.811–0.933) | 0.898 (0.837–0.952) |
| **without the 5 disclosed pairs** | 295 | **0.897** (0.861–0.929) | **0.882** (0.819–0.940; 0.806–0.931), 90/102 | **0.896** (0.835–0.951) |
| without any text match to a v4/v5 item | 289 | 0.895 (0.856–0.928) | 0.878 (0.808–0.938; 0.798–0.929), 86/98 | 0.894 (0.833–0.949) |
| strict: also v5 reserve and first-slice (dev) text, with within-slice repeats collapsed | 198 | 0.874 (0.824–0.918) | 0.815 (0.714–0.905; 0.705–0.891), 53/65 | 0.820 (0.706–0.920) |

- The 5 disclosed pairs are 2 gold supports and 3 gold refutes, and all 5 were labeled correctly. Dropping them leaves every threshold passing. The `refutes` CI lower bound still clears 0.80 (bootstrap 0.819).
- The broader "items" match adds 6 pairs (5 from v4, 1 duplicated), all gold supports or refutes. The point estimates still pass, but the Wilson lower bound for `refutes` precision dips to 0.798.
- **Strict variant.** About a third of the fresh SUPPORTS/REFUTES claims repeat a v5 reserve text, because FEVER mutations reuse short templates. 5 repeat a first-slice claim. None of those 5 was in the 65-pair dev subset the prompt was iterated on, so the prompt never saw them. 13 claims repeat within the slice.
  - Removing all of these drops 102 pairs, almost all of them correct gold supports or refutes. All 12 false refutes stay in.
  - `refutes` precision falls to 0.815 (53/65). The point estimate passes, but the CI no longer clears 0.80.
  - The duplicated claims are easy, so this variant is the conservative bound.

### Cost

The CLI version changed the cost per call. With CLI 2.1.307, each unique prompt writes a 1-hour prompt-cache entry, about 1,360 tokens. A live call costs about **$0.0046**, against about $0.0010 for 0.1.0 on 2.1.306. Repeated identical prompts, such as the regenerations, cost about $0.001.

| part | live calls | USD |
|---|---|---|
| development (2 probes of 4–5 pairs, 1 manual probe, iterations 1–2 of 95 calls each) | ~200 | ~1.10 |
| final FEVER slice | 300 | 1.388 |
| final SciFact slice | 150 | 0.893 |
| injection + clean bases | 60 | 0.426 |
| stability | 50 | 0.052 |
| **total for 0.2.0** | ~760 | **~3.86** |

The median latency on FEVER was 3.1 s.

### Caveats

- The FEVER NEI labels are noisy for this use. FEVER NEI means the annotators found no evidence in all of Wikipedia. Some BM25 top-1 passages do contradict the claim on a strict reading, so part of the remaining NEI→`refutes` rate may not be checker error.
- Same-domain caveats as 0.1.0 (§7 item 4): public data, clean text, and not v4/v5 captures.
- `run_checks_v5.py check --expect-checker` still defaults to `76d44ce2…`. Using 0.2.0 needs that default, or the policy's `accepted_checkers`, updated by their owners.

### Reproduce

```sh
PY="tools/corpus/.venv/bin/python -I"
$PY tools/evidence/support/validation/fresh_v2.py build    # deterministic; hashes above
$PY tools/evidence/support/validation/fresh_v2.py run      # live calls (cached ones are skipped; regeneration is always live)
$PY tools/evidence/support/validation/fresh_v2.py report   # writes validation/<checker_id>.json
```

---

## Checker 0.1.0: `76d44ce22b1ea2f476539e36daacc81a` (previous)

Checker `76d44ce22b1ea2f476539e36daacc81a`: Claude Code CLI 2.1.306, `claude -p --model claude-sonnet-5-5 --effort low`, all tools off. The full identity is in `validation/76d44ce22b1ea2f476539e36daacc81a.json` under `checker`. Run on 2026-10-21. No human labels were used.

**Result: all four spec thresholds pass on the public SciFact slice.** **Accepted** on 2026-10-22 by the author, on the public slice alone. This deviates from spec §2.2 item 1, which asked for a human-labeled slice of v4 captures. See `real-agent-eval/v4/PREREGISTRATION.md` §13, Amendment 1. This `checker_id` may now be listed in `accepted_checkers`. If the human slice is labeled later, it is a sensitivity analysis. Item 4 below lists the reasons the public slice is weaker evidence.

| Threshold (spec §2.2, open question 9) | Result | 95% CI | Pass |
|---|---|---|---|
| macro-F1 ≥ 0.70 | **0.866** | 0.829–0.903 (bootstrap) | yes |
| `refutes` precision ≥ 0.80 | **0.880** | 0.811–0.940 (bootstrap) | yes, and the CI lower bound clears 0.80 |
| prompt-injection success ≤ 5% | **0/50 = 0%** | 0–7.1% (Wilson) | yes on the point estimate; the CI upper bound does not exclude 5% |
| regeneration stability ≥ 95% | **48/50 = 96%** | 86.5–98.9% (Wilson) | yes on the point estimate only |

## 1. Slice

- **Source.** SciFact (`real-agent-eval/v4/benchmark/downloads/scifact/`), train and dev claims (CC BY 4.0) with their cited abstracts (ODC-By 1.0). The test split has no labels.
- **Pairs.** One (claim, abstract) pair per claim.
  - SUPPORT and CONTRADICT pairs use the lowest-id evidence abstract. Claims whose evidence labels are mixed are dropped, the same rule as `G-SCI-1`.
  - NEI pairs use the lowest cited doc id of a claim with no evidence. The cited abstract is on the same topic but is not a rationale, which makes these harder than random NEI pairs.
  - Gold labels map SUPPORT→supports, CONTRADICT→refutes, NEI→not_enough_info.
- **Exclusion.** The 290 `v4-scifact*` ids in `items_confirmatory.jsonl` (250) and `items_dev.jsonl` (40) are excluded, matched by id `v4-scifact<split><claim id>`. The check is asserted in `validate.py build`. Abstracts are not deduplicated against the benchmark; only claims are.
- **Sampling.** Seed 20261021, stratified: 100 supports, 100 refutes, 100 not_enough_info. From the same shuffle there is a disjoint pilot of 10+10+10 and disjoint injection bases.
- **Hashes.** `validation/slice.jsonl` sha256 `eae58b7344ea520dd43858f073ffa20aefb2553b3555cdd0c61527e82cf76491`; `pilot.jsonl` `0f3ecec5…`; `injection.jsonl` `ad4c5564…`. The full hashes are in the report.
- **FEVER is not used.** `downloads/fever/paper_dev.jsonl` has Wikipedia page and sentence ids but no sentence text. That would require downloading the FEVER wiki dump, so the public slice is SciFact only.
- **Spans.** The median abstract is 1,347 chars, and 290 of the 300 texts fit in 3 × 1,000 chars, so they are sent whole. The other 10 go through BM25 ranking. Mean span chars per check: 1,611.

## 2. Model choice (pilot)

Two non-collector models were run on the 30-pair pilot, which is disjoint from the slice. The rule was fixed beforehand: higher pilot macro-F1 wins.

| model | pilot macro-F1 | pilot accuracy |
|---|---|---|
| `claude-haiku-4-5-20251001` | 0.762 | 0.767 |
| `claude-sonnet-5-5` | **0.794** | 0.800 |

The pilot ran on an earlier `check.py`, so its `checker_id`s differ. Prompt, flags and model are the same as the final checker apart from the record-shape changes.

## 3. Results (n = 300)

Confusion matrix (rows gold, columns predicted). `unchecked` means the hosted model's safeguards refused the input (`refused`, sealed as `parse_error`). These are scored as wrong.

| gold \ pred | supports | refutes | not_enough_info | unchecked |
|---|---|---|---|---|
| supports | 84 | 2 | 13 | 1 |
| refutes | 4 | 88 | 6 | 2 |
| not_enough_info | 3 | 10 | 86 | 1 |

| class | precision (bootstrap 95%) | recall (bootstrap 95%) | F1 |
|---|---|---|---|
| supports | 0.923 (0.863–0.976) | 0.840 (0.762–0.909) | 0.880 |
| refutes | 0.880 (0.811–0.940) | 0.880 (0.812–0.941) | 0.880 |
| not_enough_info | 0.819 (0.745–0.894) | 0.860 (0.792–0.923) | 0.839 |

- **Accuracy:** 0.860 (Wilson 0.816–0.895).
- **Restricted to the 296 non-refused items:** macro-F1 0.872.
- **Bootstrap:** 2,000 resamples, seed 20261021. Wilson intervals are also in the report.
- **Errors that matter for scoring.** `refutes` zeroes an item, and 10 of the 100 NEI pairs were labeled `refutes`. These are on-topic abstracts that say nothing about the claim. The most common error overall is supports→NEI (13), which costs a supported item half its support factor.
- **Refusals.** 4 of 300 slice items (1.3%) and 1 of 10 clean injection bases were refused by Sonnet 5.5's biology safeguards (one example: an anthrax-spore claim). The refusal is stable for a given input, so it is sealed (`parse_error`, null label) and cached rather than retried. Expect the same on bio-security-adjacent captures.

## 4. Prompt-injection suite (n = 50)

- **Construction.** There are 10 attack templates × 5 base pairs. The payload is inserted mid-abstract. In 30 items, bases with gold refutes or NEI are pushed toward `supports`. In 20 items, supported bases are pushed toward `refutes`, because refutes zeroes an item.
- **Attack templates.**
  - `ignore_previous` ("ignore previous instructions…")
  - `fake_delimiter_close` (`PASSAGE>>>` then a fake SYSTEM turn)
  - `lookalike_delimiter` (‹›› / ＞＞＞ closes)
  - `json_prefill` (`{"label": …, "confidence": 10000}`)
  - `zero_width_hidden` (U+200B-separated instruction)
  - `markdown_role` (`### Developer message`)
  - `note_to_checker`
  - `test_instruction`
  - `multilingual` (French and German)
  - `html_comment` (`<!-- assistant: label=… -->`)
- **Reach.** All 50 payloads reached the prompt; the BM25 spans included them.
- **Result.** The target label was output 0/50 times, and 0/50 changed the label relative to the clean base. 2/50 were refused. The neutralizer had already rewritten the two delimiter attacks before the model saw them; the other eight reached the model verbatim.
- **Size.** The suite meets the spec's ≥ 50. It is small, though: the 95% upper bound of 7.1% does not formally exclude the 5% threshold.

## 5. Stability (regeneration, n = 50)

50 slice pairs (seed 20261022) were queried again with the cache bypassed. 48/50 labels (96%) and 28/50 `score_q` values were identical. The CLI exposes no temperature or seed control, so this measures the drift of regeneration on a hosted model; it is not replay. This is why labels are sealed: replay reads the sealed label and never re-runs the checker (spec §4). The regeneration pass was run twice, and the report keeps the second. The first pass was not kept, so its agreement is not reported. 96% clears 95% only on the point estimate.

## 6. Cost and time per check

Live calls only (cache hits cost nothing). Six calls in parallel.

| set | live calls | mean cost | median latency | p90 latency |
|---|---|---|---|---|
| slice | 300 | $0.0010 | 2.96 s | 3.59 s |
| injection + clean bases | 60 | $0.0012 | 3.88 s | 4.84 s |
| stability | 50 | $0.0011 | 2.89 s | 3.43 s |

- **Throughput.** 300 checks took about 155 s wall clock with six workers.
- **Cold start.** The first pilot calls cost about $0.006 each. Later calls are cheaper because the CLI's prompt cache covers the fixed system prompt.
- **Total spend** for the checker validation, all runs including pilots and re-runs after `checker_id` changes: about $2.
- **Cache.** Results are cached by (checker_id, rendered prompt), so repeated runs re-query only the regeneration set.

## 7. What is still needed before use

1. The human slice: at least 200 pairs from v4 captures, two-way blind, 3-way guide, in the label sheet. Then re-run `validate.py report` with that slice added, and bind it to this `checker_id`.
2. Decide whether a larger injection suite (≥ 100) is wanted so that the CI upper bound falls below 5%.
3. Decide how to treat safeguard refusals in scoring. Today they are `parse_error`, so the item is unchecked with factor 1.0.
4. The public slice is weaker evidence than the human slice in four ways:
   - SciFact abstracts are short, clean scientific prose. v4 captures are long, noisy web pages (navigation, boilerplate), where span selection matters much more; see the smoke test.
   - The NEI pairs are drawn from cited abstracts, a specific distribution.
   - Sonnet may have seen SciFact during training.
   - The slice is one domain only.

## Reproduce

```sh
python3 -I tools/evidence/support/validate.py build    # deterministic; hashes above
python3 -I tools/evidence/support/validate.py run      # live calls (cached ones are skipped)
python3 -I tools/evidence/support/validate.py report   # writes validation/<checker_id>.json
```
