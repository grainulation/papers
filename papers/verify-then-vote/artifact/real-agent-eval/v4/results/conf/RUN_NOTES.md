# v4 confirmatory analysis: run notes

Run 2026-10-23, after the Amendment 6 analysis hold was lifted (v5 preregistration frozen, v5
confirmatory analysis done).

## What was run

1. All `FREEZE.json` hashes (PREREGISTRATION.md, item files, manifest, answer_key.py, canon.py,
   collect_v4.py, evaluate_v4.py) and the frozen binary hash (`43c55b36…`) verified before the
   run; all matched. The non-frozen imports (`v3/evaluate_v3.py`, `evaluate_v2.py`,
   `collect.py`, `evaluate_v1.py`, `v4/canon`, `v4/power`) have no commits since the binary's
   build commit 9e27f29.
2. Preregistered analysis, run once (29.9 s wall, exit 0):

   ```
   cd real-agent-eval/v4
   python3 evaluate_v4.py --split conf --bin frozen-bin/bran-v4-eval --m11-model qwen2.5_3b
   ```

   Output goes to `results/conf/` (the code's default for `--split conf`, matching §11.2.6).
   stdout/stderr in `evaluate_stdout.txt` / `evaluate_stderr.txt`. Mirror check: 2,995 slots,
   0 mismatches.
3. `amendment5_h4_s9_s10.py` (written after the freeze; see deviations) computes H4, S9, the
   Amendment 5 S4-split and S10 into `amendment5_v4.json` and `s10_per_item_v4.csv`.

## Deviations and notes

- **H4, S9 and S10 are not in the frozen `evaluate_v4.py`.** The code was frozen before
  Amendments 3 (S9) and 5 (H4, S10). As those amendments specify, H4 and S9 are computed from the
  frozen per-item table `paired_decisions_v4.csv` with the frozen `newcombe_paired` and
  `mcnemar_p` (imported from the hash-checked `evaluate_v4.py`, not re-implemented). The H4
  result equals H1's Newcombe interval in `evaluation_v4.json`.
- **S10 machine not idle.** Amendment 5 asks for replay "on an otherwise idle machine". Another
  agent was active; load average 4.4–4.5 at start and 4.4 at end (`s10_load.txt`). Times are
  therefore upper-bound-ish. Each reduction: 1 warm-up + 5 timed runs, median kept; time
  includes process spawn. Replay outputs equal the sealed outputs on all 2,995 calls.
- **S10 generation time.** "That item's agent generation time" is taken as the item's wall span
  (first request start to last response end; the 5 agents run concurrently). The ratio to the
  summed per-agent `elapsed_s` is reported beside it.
- **S10 size.** Sealed input/certificate are the M3 `*.in.json` / `*.out.json` as written by
  `evaluate_v4.py` (pretty-printed JSON, indent 1). Ratios are given against both the raw
  response text and the whole raw record file.
- **H3, S9-H3 and the checked-evidence exploratory split not computed.** No confirmatory
  capture/support store exists for v4 (`v4/evidence-cache/` holds only pre-Stage-B captures,
  last written 2026-10-21).
- **S7 not computed.** No human labels for the confirmatory PopQA sample exist; `--labels` was
  not passed. `popqa_label_sheet.csv` is the sheet to fill.
- **No `RESULTS.md`.** §11.3 names `v4/make_results.py`; it was never written and the README
  describes no results markdown, so none was rendered.
- **`--unblind` not passed.** It is a no-op for `--split conf` in the frozen code (blinding
  applies to dev only) and the README invocation omits it.
- **Reducer I/O not committed.** `rust/` (25 MB) and `s1_rust/` (11 MB) are deterministic and
  regenerable from the committed raw records with the frozen binary (as for v5's `eval/rust/`).
  `amendment5_v4.json` records `rust_io_tree_sha256` over `rust/`.
- **No hosted calls.** Everything ran locally; cost $0.
