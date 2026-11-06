# Artifact: Verify, Then Vote

Code, proofs, preregistrations and sealed data for *Verify, Then Vote: Overturning Wrong Majorities
in Multi-Agent LLMs*. Every number in the paper can be recomputed from this
directory; the table below maps each result to the command that reproduces it. The [main paper](../paper.pdf) presents the argument; [supporting material](../supplement.pdf) contains detailed methods, proofs, and diagnostics.

All commands run from this directory (`artifact/`) unless a line starts with `cd`.

## Directory map

| path | contents |
|---|---|
| `overturn/` | the reducer (Rust crate, binary `overturn`) |
| `lean/` | Lean 4 proofs of the selection guarantees and the gate's harm bound; `lean/CATALOGUE.md` maps each statement to its theorem |
| `bindings/python/` | the Python package `overturn-arbiter`, a front end to the reducer |
| `real-agent-eval/v5/` | **OVERTURN**: benchmark, preregistration, `FREEZE.json`, frozen evaluator and binary, sealed agent responses, captures, checker labels and judge rows |
| `real-agent-eval/v6/` | the **second agent pool**: preregistration, `FREEZE.json` (82 files), pool manifest and qualification, sealed agent responses, captures, checker labels, judge rows, results and the cost script |
| `real-agent-eval/v4/` | the companion **memory-only** benchmark: preregistration, `FREEZE.json`, frozen evaluator and binary, sealed responses and results |
| `real-agent-eval/v3/`, `real-agent-eval/*.py`, `real-agent-eval/results/`, `real-agent-eval/labels/` | the **free-text** measurements: collection, evaluation and labels |
| `v3/` | design documents for OVERTURN, including the gate specification `v3/GATE_SPEC.md` |
| `v2/` | evidence-verification specification and the replay, tamper and stress outputs (`v2/evidence/`) |
| `results/workload/` | re-measured synthetic workload timings |
| `tools/evidence/` | evidence capture (`capture.py`, `corpus_capture.py`, `extract.py`) and the support checker and its validation (`support/`) |
| `tools/judge/` | the LLM judge, reader and closed-book references |
| `tools/corpus/` | the retrieval corpus builder and BM25 retrieval (`corpus_manifest.json` holds the hashes) |
| `corpus-cache/` | only the dense-index manifest; the built corpora are not distributed (see "Data") |

## Requirements

| for | needs |
|---|---|
| reducer, replay, workload | Rust 1.93 (`rustup`); `cargo build --release --locked` in `overturn/` |
| proofs | elan with Lean 4.35.0 (pinned in `lean/lean-toolchain`) and Mathlib v4.35.0 via `lake exe cache get` (prebuilt oleans, about 7 GB) |
| analyses | Python 3.12 or later with numpy (pinned in `requirements.txt`; `evaluate_v5.py` and `real-agent-eval/v4/evaluate_v4.py` import it); `make_results.py` and `tools/evidence/extract.py` use the standard library only; the analyses were checked with 3.14.3 and the test suites with 3.12.4 |
| Python tests, retrieval | `pip install -r requirements.txt` (pinned: bm25s 0.3.14, numpy 2.4.4, scipy 1.18.1, pytest 9.1.1) |
| paper | Tectonic (tested with 0.17.0) or TeX Live; `make` in `../tex/` |
| re-collection only | Ollama 0.17.7 with the five agent models at the digests below, and `nomic-embed-text` for the SciFact dense index |
| re-checking and re-judging only | access to the hosted checker and judge model named in `tools/evidence/support/pin.json` and `tools/judge/pin.json` |

Agent model digests (from `real-agent-eval/v5/results/conf/run_manifest.json`, the same as v4):

| model | digest | quantization |
|---|---|---|
| `llama3.2:3b` | `a80c4f17acd55265feec403c7aef86be0c25983ab279d83f3bcd3abbcb5b8b72` | Q4_K_M |
| `mistral` | `6577803aa9a036369e481d648a2baebb381ebc6e897f2bb9a766a2aa7bfbc1cf` | Q4_K_M |
| `gemma2:2b` | `8ccf136fdd5298f3ffe2d69862750ea7fb56555fa4d5b18c04e3fa4d82ee09d7` | Q4_0 |
| `phi3:mini` | `4f222292793889a9a40a020799cfd28d53f3e01af25d48e06c5e708610fc47e9` | Q4_0 |
| `qwen2.5:3b` | `357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b` | Q4_K_M |
| `nomic-embed-text` (dense retrieval) | `0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f` | F16 |

Second-pool agent digests (from `real-agent-eval/v6/pool_manifest.json`, which also records each model's license text):

| model | digest | quantization | license |
|---|---|---|---|
| `falcon3:3b` | `784a7eab5b891a30c0b57300c1c6da7022b02665fc5a12c1c817650575c10917` | Q4_K_M | TII Falcon License |
| `olmo2:7b` | `4208d3b406db076e1569c97a2fb67cf9c86b845544c1a61ff218259daf9e3538` | Q4_K_M | Apache 2.0 |
| `exaone3.5:7.8b` | `c7c4e3d1ca22fe9225f18b35eb719f67e2ca96a42e7fd17294a45b83ba8fbf03` | Q4_K_M | EXAONE AI Model License 1.1, non-commercial |
| `nemotron-mini:4b` | `ed76ab18784f5a01c9ec5b3c250e964d4f9c7a983e59ba041bb995f0fe2e8fb3` | Q4_K_M | NVIDIA AI Foundation Models Community License |
| `granite3.3:2b` | `07bd1f170855240f9e162bf54ea494a8bc1c73d8cbd1365d7fccbeb7d2504947` | Q4_K_M | Apache 2.0 |

No model and no hosted call is needed to reproduce the analyses: they read the sealed records.

## Quick start

For the two evidence-grounded studies, build the reducer on your platform and reconstruct the published decisions using Python 3.12 or later and NumPy:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install numpy==2.4.4
make portable-reanalysis PY=.venv/bin/python
```

This runs both OVERTURN (v5) and the second pool (v6), verifies the frozen input hashes with exact documented publication redactions, and compares the resulting decision files byte for byte with the published records. It also checks all 7,910 v5 root hashes and certificates. Statistical JSON and figure data are also compared, allowing only relative floating-point roundoff of 1e-12 (zero absolute tolerance); integer counts, decision files and certificates remain exact. The v5 results tables are regenerated and compared with only runtime and binary-identity fields masked. No model service, API key or original macOS binary is needed. Cargo downloads its pinned dependencies on the first build.

Outputs go to `bench-output/portable-v5/` and `bench-output/portable-v6/`. Each `reconstruction.json` records the rebuilt binary identity and comparison result. Existing output directories are refused; use a fresh `OUT` directory for another run. These runs are explicitly source-rebuilt reconstructions, not replays with the historical frozen executable.

Additional checks:

```sh
.venv/bin/python -m pip install -r requirements.txt
make test                              # reducer tests
make lean                              # proofs; downloads the Mathlib cache
make python-test PY=.venv/bin/python   # Python suites
.venv/bin/python -m unittest discover -s reproduction -p 'test_*.py'
```

`make overturn-reanalysis` and `make secondpool-reanalysis` run the same public reconstruction one study at a time, under `bench-output/overturn/` and `bench-output/secondpool/`. `make memoryonly-reanalysis` reconstructs v4, including Amendment 5, with the rebuilt reducer and compares results while excluding execution timings and binary provenance. `make reproduce` includes these portable paths and the proof/test suites. To run everything after the quick start without reusing its outputs, use `make reproduce PY=.venv/bin/python OUT=bench-output/full`.

## Additional reviewer analyses

These analyses are post hoc and leave the original protocols and frozen records unchanged. They need no model calls.

```sh
make build
.venv/bin/python reproduction/matched_gate.py --bin overturn/target/release/overturn --out bench-output/matched-gate
.venv/bin/python reproduction/audit_validation.py --out bench-output/validation-audit
```

Both output directories must be new. [The matched gate analysis](reproduction/MATCHED_GATE.md) holds all other settings fixed at each of two evidence factors: harmful overturns fall from 23 to 12 and from 33 to 12, with fewer corrections in both cases. It checks all 4,400 reductions against the independent mirror and the original configurations against the archive.

[The validation-channel audit and review packet](reproduction/calibration_audit/README.md) distinguish 18/350 raw false supports from 22/350 raw false refutes. The historical forecast is retained for transparency; its exposure and polarity mismatches prevent a calibrated deployment-harm interpretation. The packet contains 82 blank independent human-review forms, **not completed human validation**.

## Results and how to reproduce them

The rows follow the supporting reproduction guide. "Checked" means the command was run on the
provided artifact and gave the expected output; the platform was macOS 26 on Apple silicon.

| result in the paper | command | expected output | status |
|---|---|---|---|
| Lean proofs | `make lean` | `Build completed successfully`; `Audit.lean` prints 32 `#print axioms` lines, each listing only `propext`, `Classical.choice`, `Quot.sound` (no `sorryAx`) | checked |
| Unit and property tests, Schulze equivalence | `make test` | `132 passed; 0 failed; 1 ignored` | checked |
| In-memory replay | `make test-quick` | `700/700 property checks passed`; `All 5 topics × 100 replays = 500 total compilations identical.` | checked |
| From-file replay and tamper rejection | `make replay-file` | 5 topics dumped and replayed (root hashes as in `v2/evidence/replay-v4/README.md`, e.g. tcp `9bfc91230c6bb7612855ebc548567eb1`, cert `19f12d080acac5d2`); every line starting with `PASS`, policy tampers exit 4, kept-id claim edit exit 3, format retag exit 5, envelope edit exit 6. The `FAIL ...` lines printed by the reducer are its rejection messages for the tampered files. | checked |
| Cross-build replay and tamper tables | Docker and Rosetta commands in `v2/evidence/replay-v4/README.md`; then `python3 -I v2/evidence/replay-v4/compare.py` | dumps byte-identical across the 4 builds, replay matrix 80/80, tamper cases 36/36 with the expected exit codes; `compare.py` prints `ALL IDENTICAL / ALL PASS` | `compare.py` on the committed dumps and logs: checked (its output equals the committed `results/compare.txt`); the four builds themselves: not re-run |
| Synthetic workload tables and margins | `make workload` (`--stress`, `--pass-timing`, `--score-gaps`, `--baselines`, `--ablation`, seed 42) | claim counts, slots, false positives, precision, score gaps, baseline and ablation tables equal to `results/workload/` and `v2/evidence/stress/`; timings vary by machine (`results/workload/summarize.py` computes the medians over runs) | checked (non-timing values identical) |
| OVERTURN: preregistered tests | `make overturn-reanalysis` | `PASS v5: source-rebuilt decisions match published records` (statistical JSON and rendered tables checked as described above), and `PASS 7910 root hashes and certificates match results/conf/eval/certificates_v5.jsonl`. In `bench-output/overturn/evaluation_v5.json`: H1a b = 91, c = 12, p = 3.46e-16 (accuracy 71.5% to 86.5% on 526 decisive conflicts); H1b b = 99, c = 23; H3a c = 12, upper bound 0.0551; H3b b = 9, c = 1; H4 c_D = 10, F = 56, F-hat = 52.75 (historical exposure proxy, not a calibrated checker-error forecast), harm condition holds | checked |
| OVERTURN: sources, references, replay, leave-one-agent-out, cost | same run; `bench-output/overturn/RESULTS.md` | the source table, the judge and oracle gap rows, replay identity 1100 / 1100, leave-one-agent-out 3510 re-decisions with 330 changed, the cost table; only reducer wall times differ from the committed `results/conf/RESULTS.md` | checked |
| Passage control | `real-agent-eval/v5/controls/controls_v5.py` (calls the hosted checker); outputs included in `real-agent-eval/v5/controls/` | 0 of 236 pairs labeled supports in each condition (passage withheld; passage replaced); re-decided accuracy 74.0% (`RESULTS.md`) | provided; re-running needs the hosted checker |
| Second pool: preregistered tests | `make secondpool-reanalysis`: `reproduction/portable.py --study v6` runs the frozen evaluator with a rebuilt reducer and validates decision files and statistical JSON; `make_results_v6.py` and `pooled_h3a_v6.py` render `RESULTS.md` and the pooled bound | per-item decisions identical to `real-agent-eval/v6/results/conf/eval/`; verified default first b = 73, c = 3, p = 1.94e-18, upper bound 0.0218; scored rule b = 80, c = 8, upper bound 0.0390; pooled 20 / 776, upper bound 0.0395 | checked |
| Cost with label reuse | `python3 real-agent-eval/v6/cost_v6.py` (reads the call logs of both pools; no model call) | `results/conf/cost_v6.json`: $0.0212 per contested decision at original prices, $0.0114 in new calls, 49% of cited checks reused | checked |
| Verified default first on the first pool, checker wording, two-way checker | `real-agent-eval/v5/selector_study/`, `real-agent-eval/v5/harm_attribution/` (wording test calls the hosted checker), `real-agent-eval/v5/local_checker/` (needs the local model) | 87 / 4, upper bound 0.0270; label flips 2.6 to 5.7% against 4.4% re-query; 87.3% to 77.8% with the two-way checker | provided |
| Verified wrong answers | `real-agent-eval/v5/controls/harm_reading.jsonl` | 82 pairs on 56 items, two same-family model annotators (kappa 0.95) plus model adjudication; not independently human-validated: 24 checker false support, 8 entity mismatch, 5 false source, 19 gold (9 alias, 3 alternative, 7 source-gold disagreement); lost defaults 5, 1, 1, 3 | provided |
| OVERTURN: root hashes and certificates of the sealed sets | `make overturn-certificates` (run by `make overturn-reanalysis`); reference `real-agent-eval/v5/results/conf/eval/certificates_v5.jsonl` | `PASS 7910 root hashes and certificates match results/conf/eval/certificates_v5.jsonl`: one record per reduction (1,100 items × B0, BE, BE-G, EO, plus 3,510 leave-one-agent-out re-decisions) with item id, method, configuration, policy template SHA-256, policy hash, root hash and certificate | checked |
| OVERTURN: cross-check with a rebuilt reducer | `make build overturn-crosscheck` (after `make overturn-reanalysis`) | `7910 reductions replayed ...: 7910 identical, 0 differ` | checked (same platform) |
| OVERTURN: benchmark and corpus build | `real-agent-eval/v5/benchmark/README.md`, `tools/corpus/README.md` (downloads the datasets) | item files and corpus hashes equal to `real-agent-eval/v5/benchmark/manifest.json` and `tools/corpus/corpus_manifest.json` | not re-run (needs the dataset downloads) |
| OVERTURN: collection, checks, judges | `real-agent-eval/v5/README.md`, `tools/evidence/support/run_checks_v5.py`, `tools/judge/` | new raw records, checks and judge rows | not re-run (needs the models and the hosted checker and judge) |
| Support-checker validation | `tools/evidence/support/validate.py build | run | report` (see `tools/evidence/support/VALIDATION.md`); the frozen report is `tools/evidence/support/validation/f2a14bd8988371bd231ca6ff137be13e.json` | the checker validation table | not re-run (`run` calls the hosted model) |
| Memory-only benchmark | `make memoryonly-reanalysis` | `compare with results/conf/: no differences outside timing and path fields`; in `bench-output/memoryonly/`: H1 (M3 vs M2) b = 45, c = 58, p = 0.237, not rejected; Amendment 5 H4 Newcombe 95% CI [-0.111, 0.023], so non-inferiority at -0.10 is not shown; S10 replay mismatches 0 | checked |
| Free-text study: tables and margins | `(cd real-agent-eval/v3 && python3 make_results.py)`; `python3 ../tex/figures/make_fig3_data.py` | `RESULTS.md` and the four `fig3-*.dat` files byte-identical to the committed ones (both scripts rewrite them in place) | checked |
| Free-text study: identifier recovery | `make freetext-identifiers` | 332 unique identifiers; `PASS identifier recovery matches tools/evidence/results/` | checked |
| Free-text study: collection, evaluation, capture, attachment | `real-agent-eval/v3/README.md`, `tools/evidence/README.md` | as described there | not re-run (collection needs the models; `evaluate_v3.py` rewrites `real-agent-eval/v3/results/` in place and was run with a separately built binary, sha256 `263469c2…` in `real-agent-eval/v3/results/build_provenance.json`, that is not included; capture needs the network) |

The Python test suites (`make python-test`) cover the capture tool, the support checker, the judges,
the corpus tools, the v4 canonicalizer and the v5 evaluator on synthetic records: 257 passed and 35
skipped without a reducer binary; with `OVERTURN_BIN=overturn/target/release/overturn` (or after
`make build`) the 24 end-to-end evaluator tests also run, giving 281 passed and 11 skipped. The
skipped tests need the built corpora (see "Data") or an optional package (`langgraph`).

The Python package is tested separately:

```sh
cd bindings/python
python scripts/build_wheel.py --cargo --target-dir /tmp/overturn-target --outdir /tmp/dist
pip install /tmp/dist/overturn_arbiter-0.1.0-*.whl
OVERTURN_TEST_INSTALLED=1 python -m pytest -p no:cacheprovider
```

which bundles a reducer built from `overturn/` and gives 40 passed, 1 skipped (the LangGraph test).

## Platform notes

- The archived executable copies are sanitized macOS arm64 executables; their exact historical filenames are listed in [COMPATIBILITY.md](COMPATIBILITY.md). The manifests retain their original historical hashes; publication hashes are recorded in `FROZEN_REDACTIONS.md`. Public reconstruction builds from source instead of executing these copies.
- `make portable-reanalysis` rebuilds the reducer for Linux or macOS. Its wrapper verifies all original v4/v5/v6 freeze entries against their frozen hashes or the exact old/new pairs in `FROZEN_REDACTIONS.md`, then substitutes only the expected binary hash in the evaluator's in-memory freeze lookup. The wrapper does not modify source, data or freeze manifests at runtime; publication redactions are documented separately. The evaluator records the actual rebuilt binary hash; decisions are checked against the published reference.
- This portable route covers v5 and v6 decisions and v5 certificates. It does not claim reproduction of historical wall-clock timings. The separate `make memoryonly-reanalysis` target includes the v4 Amendment 5 analysis with a rebuilt binary. The results table records the original publication checks; the current targets reconstruct those results using the source-built reducer.
- `make lean` downloads about 7 GB of Mathlib build files; without `lake exe cache get`, Lake
  builds Mathlib from source, which takes hours.
- Wall-clock values (reducer and replay timings, S10) depend on the machine and its load. The
  re-analysis targets mask only named runtime/provenance fields. Decisions, counts and certificates compare exactly; v5/v6 statistical floats allow relative roundoff of 1e-12 with zero absolute tolerance.

## Data and frozen files

- Licenses of the third-party text in this artifact, and the files that contain it, are listed in
  [`DATA_LICENSES.md`](DATA_LICENSES.md). FEVER-derived text is CC BY-SA 3.0.
- The full FEVER Wikipedia dump, the SciFact corpus, the dataset downloads and the retrieval indexes
  are not distributed. `tools/corpus/build.py` and the benchmark build scripts download them and
  check them against the recorded hashes. Tests that need them skip with a message naming the
  missing input.
- `real-agent-eval/v5/results/conf/eval/certificates_v5.jsonl` is the trusted reference for the
  sealed sets: it records the root hash, policy hash and certificate of each of the 7,910 OVERTURN
  reductions, so a copy of any sealed set or a re-run can be checked against it
  (`make overturn-certificates`; `real-agent-eval/v5/certificates.py` writes and checks the file).
- `real-agent-eval/v4/FREEZE.json`, `v5/FREEZE.json` and `v6/FREEZE.json` preserve the original frozen identities. Publication redactions remove private build paths and metadata; [`FROZEN_REDACTIONS.md`](FROZEN_REDACTIONS.md) records exact original and published hashes. Public reconstruction wrappers accept only those recorded pairs.
- Historical evaluators and collectors retain their original integrity checks. They may refuse sanitized published files or binaries when invoked directly. Use `make portable-reanalysis` and `make memoryonly-reanalysis` for the public artifact; these wrappers validate frozen inputs first and explicitly record the reconstructed binary identity. No original private files or model services are required.

## Public names and compatibility

The Rust crate and CLI are `overturn`; the Lean library is `OverturnLean` (namespace `Overturn`); the Python distribution/import are `overturn-arbiter` / `overturn_arbiter`.

Frozen data-format identifiers, archived filenames, and collection provenance retain their exact bytes so the study can be reproduced. They are documented separately in [the compatibility boundary](COMPATIBILITY.md). Current commands and configuration use the public names. No earlier public release is implied by the study's internal formats or freezes.
