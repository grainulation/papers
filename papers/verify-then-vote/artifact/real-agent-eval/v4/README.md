# Eval v4: collection and analysis code

This directory holds the eval-v4 benchmark, canonicalizer and power analysis (frozen; see
`FREEZE.json`), the preregistration (`PREREGISTRATION.md`, frozen), and the code that runs it:

| file | role |
|---|---|
| `collect_v4.py` | collector (§7, §11.1), fork of `v3/collect_v3.py` |
| `evaluate_v4.py` | analysis (§3–§6, §11.2) |
| `CODE_FREEZE_PROPOSAL.json` | sha256 of the two scripts, for the analysis team to add to `FREEZE.json` before Stage B |
| `STAGE_A.md` | Stage A (dev) report: parse audit, yield, discordance, implied item count |
| `results/build_provenance.json` | the reducer binary used, its sha256 and the source hashes it was built from |
| `results/dev/` | Stage A raw records, manifest and blind analysis outputs |

## Collection (`collect_v4.py`)

- Start-up checks, each aborting on failure:
  - every hash in `FREEZE.json`;
  - model digests equal to `v3/results/run_manifest.json`;
  - Ollama version and the server env (`OLLAMA_NUM_PARALLEL`, `OLLAMA_MAX_LOADED_MODELS`, …)
    from the server startup log, recorded. Set `BRAN_OLLAMA_LOG` to the log file for your
    Ollama installation when collecting new records.
- The digests are read from `/api/tags`. This Ollama build's `/api/show` returns no digest
  field, so its `details` and a modelfile hash are recorded alongside.
- **Prompts.**
  - The system prompt is `SYSTEM_PROMPT_V4` (`benchmark/manifest.json`): the v3 prompt plus the
    instruction to end with `ANSWER: <your answer>`.
  - The user prompt is the item's `prompt`, verbatim. It already ends with the per-type
    instruction: an option letter, SUPPORTED/REFUTED, or a name.
- **Options and dispatch.**
  - Options are temperature 0.7, num_predict 1024, seed 42, with a 900 s timeout.
  - All 5 requests for an item are dispatched concurrently, in an order shuffled by
    `random.Random(20261101)`, with one shuffle per item in frozen `order`. Items run
    sequentially.
  - One lock-protected sequencer assigns `arrival_seq` when the body of the successful attempt
    has been fully read.
- **Retries.** A failed request is retried up to 2 times with the same seed. Failed attempts
  are kept in `attempts`, without a sequence number.
- **Resumable.** An item whose raw file exists is skipped, and its stored dispatch order is
  checked. The sequencer resumes after the largest stored `arrival_seq`. Files are written
  atomically.
- **Stage B guard.** `--split conf` refuses to run unless `FREEZE.json` lists the sha256 of
  `collect_v4.py` and `evaluate_v4.py` and both match the files on disk.

```
python3 collect_v4.py --split dev                       # Stage A
python3 collect_v4.py --split conf --n-items I          # Stage B, after the code freeze amendment
```

## Analysis (`evaluate_v4.py`)

- **Parse.** `answer_key.parse_answer` (gold-blind) and `answer_key.answer_line`.
- **Slot.** One exclusive functional slot `(v4-<id>, answer, ·)` per item.
  - Eligible: at least 2 parseable answers.
  - Decisive: at least one correct and at least one incorrect member under G-AK
    (`answer_key.grade`).
- **Contributions (§4.3).** Each parsed answer becomes one AFFIRM triple. Its evidence is every
  item that `evaluate_v2.load_contributions(associate=True)` attaches to the v3-extracted claims
  of the same response, de-duplicated by text. The rest:
  - UNVERIFIED and reachable;
  - lowering confidence HIGH;
  - seq = `arrival_seq`×1000, calibration 0.7;
  - id = `sha256(item|agent|answer|object)[:16]`.

  Each response also keeps its raw source/citation lines verbatim (`source_lines` in
  `responses_v4.jsonl`), because `tools/evidence/extract.py` (the capture tool) did not exist when this
  was written.
- **Rust methods** (one `overturn --reduce` per method, with policy overlays on
  `evaluate_v3.DEFAULT_POLICY`). Every method's `values.incompatible_values` is
  `{"answer": {"__all_objects__": <observed objects>}}`.

  | method | overlay |
  |---|---|
  | M1 | none |
  | M3 | weights rec 0, `schulze_dims` 23, `tiebreak_order` id |
  | M4 | rec 0, deadband 0 |
  | M5 | weights 1/0/0/0/0, deadband 0 |
  | M6 | rec 0, deadband 500, `tiebreak` score_then_canonical |

  Policy hashes are written per item and method (`policy_hashes_v4.csv`). They vary with the
  observed objects.
- **Python methods.** M2 and M7–M12, as in §5.
- **Mirror check.** A Python mirror of the single-slot reduction must equal the binary on every
  slot and method: winner, members, quantized scores and deadband. The run aborts on any
  mismatch.
- **Statistics.**
  - Exact McNemar test, the v3 definition.
  - Newcombe hybrid-score CI (method 10).
  - Item bootstrap, 10,000 resamples, seed 42.
  - Fixed sequence H1 (M3 vs M2), then H2 (M3 vs M1). H2 non-inferiority holds when the
    Newcombe 95% lower bound is above −0.10.
  - S1–S8. S7 needs a labels CSV; `popqa_label_sheet.csv` is the sheet to fill.
- **Stage A is blind.** On `--split dev` the full analysis runs, so the code path is
  exercised, but its Rust I/O goes to a temporary directory and only these are written:
  - the parse audit and per-model accuracy and parse-failure rate (S6, M11 choice);
  - yield, direction-free b+c, and the item count it implies;
  - mirror-check status and policy hashes.

  `--unblind` is refused on dev. `--synthetic-test` runs the unblinded writers on synthetic raw
  records only; the raw directory must contain a `SYNTHETIC` marker file.

```
python3 evaluate_v4.py --selftest
python3 evaluate_v4.py --split dev  --bin <overturn>                         # Stage A (blind)
python3 evaluate_v4.py --split conf --bin <overturn> --m11-model <agent>     # Stage B, once
```

## Interpretations and deviations

These are also listed in `STAGE_A.md` and should go into the §13 amendment.

1. **ψ pair.** §7 step 3.4 and §11.2.8 name M1 vs M2 for ψ_A and for the primary statistic,
   while §2 (resolution 1) makes H1 M3 vs M2.
   - `evaluate_v4.py` tests H1 as M3 vs M2.
   - Stage A reports b+c for both pairs, and the item count each implies.
   - The analysis team should state in the amendment which ψ sets I.
2. **N\* at ψ\* between Table 1 columns.** N\* is computed with `power/power.py:min_n_stable`,
   the function that produced Table 1. The next Table 1 column at or above ψ\* is reported
   beside it.
3. **Confidence of the answer contribution.** "Parsed exactly as in v3" is implemented as the v3
   hedge rule applied to the ANSWER line.
4. **ANSWER lines are removed before the v3 claim extraction.** This applies both to the
   evidence of the answer contribution and to the S1 arm.
5. **Grading a selected object (M2, M7).** The method is graded on the ANSWER line of the
   object's smallest-id member. Objects whose members grade differently are counted.
6. **The v3 `tcp_*` incompatible-value entries are dropped.** They are replaced by the `answer`
   group, exactly as the v3 "forced" policy did.
7. **Order-free choice sets.** M2's random tie-break chooses from the sorted tied objects, and
   M10 from the members sorted by id.
8. **S1 arm.** It reuses the `evaluate_v3` helpers (`build_contribs`, `lower`, `rust_outcome`,
   `ev2.majority_idx`, the graders) with canon-1.0.0 on objects, as in `canon/run_canon.py`.
   The Table A/B rows are rebuilt for M1, M3 and M2 only, so that M3 can be added. SciFact has
   no readability triple, so it is not in S1.
9. **The machine was not quiet** during Stage A: other concurrent jobs ran `rustc` and the reducer. CPU
   load was sampled every 60 s into `results/dev_load_log.txt`.
