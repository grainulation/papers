# Real-agent eval v3

Eval v3 re-runs the real-agent pilot (paper §9.2) with four changes:

1. It uses the actual Rust reducer (`overturn --reduce`), not the Python port.
2. It records real arrival order.
3. It checks Python ↔ Rust equivalence.
4. It reports the decisive-conflict yield and how to raise it. A second sampling replicate was started and then stopped; it is incomplete and unused.

All numbers are in `RESULTS.md`, which `make_results.py` generates from `results/*.json`.

## Files

| file | what it is |
|---|---|
| `collect_v3.py` | Re-collects responses from Ollama. It uses the same model list, system prompt, `temperature 0.7` and `num_predict 1024` as `../collect.py`, and imports that file's claim extraction unchanged. Each request also sets `seed`; the original collection set none. |
| `evaluate_v3.py` | Lowers the claims to the `--reduce` schema, runs the binary under several policies, runs the Python-mirror ladder for the equivalence check, and scores with both graders from `../evaluate_v2.py`. |
| `make_results.py` | Renders `RESULTS.md`. |
| `results/raw/<qid>.json` | Full record per question: dispatch order, arrival order, per-response wall and monotonic start/end times, `arrival_seq`, Ollama timing metadata, raw text, and `/api/ps` samples taken every 2 s. |
| `results/<qid>.json` | v1-compatible response list ordered by arrival. It adds `arrival_seq`, `arrival_rank`, `list_index` and `dispatch_index`. |
| `results/run_manifest.json` | Model digests, `ollama list` output, options and seeds. |
| `results/build_provenance.json` | Binary sha256, per-file reducer source hashes at build time, rustc version, and the Ollama server config. |
| `results/rust/<dataset>/<qid>/<policy>.{in,out}.json` | Every `--reduce` input and output. |
| `results/evaluation_v3.json` | All summary statistics. |
| `results/equivalence_<ds>.csv` | One row per Python conflict set: the Python winner, the Rust outcome, agreement, and the ladder cause. |
| `results/paired_decisions_<ds>_<table>_<grader>.csv` | Per-conflict paired correctness for every method. |
| `results/separation_margins_<ds>_<table>_<grader>.csv` | Evidence and total-score gaps on decisive sets, taken from the Rust scores. |
| `results/arrival_order*.csv` | Per-question list, dispatch and arrival order, and Kendall tau. |
| `results/precision_adjudication_<ds>.csv` | Rust-admitted contributions that fail the stricter grader. `human_label` is **empty**, for the author to fill. |
| `results_rep2/` | **INCOMPLETE, unused.** Replicate 2 (request seed 43, dispatch seed 20261022) was stopped on request after 18 of 55 questions. No table uses it. |

## Exact commands

```sh
cd real-agent-eval/v3

# 1. collection (about 45 min per replicate on the author's 36 GB Mac)
python3 collect_v3.py                       > results/collect_log.txt 2>&1
# (replicate 2, NOT completed / not used:)
# python3 collect_v3.py --out results_rep2 --request-seed 43 --dispatch-seed 20261022

# 2. Rust binary (own target dir; record its hash)
(cd ../../overturn && cargo build --release --target-dir "$SCRATCH/target-eval")
cp "$SCRATCH/target-eval/release/overturn" "$SCRATCH/bran-v3-eval"
shasum -a 256 "$SCRATCH/bran-v3-eval"      # 263469c2...136df83 for the reported run

# 3. evaluation + report
python3 evaluate_v3.py --bin "$SCRATCH/bran-v3-eval" --bootstrap 10000 --seed 42 \
        --datasets v3 v1orig
python3 make_results.py
```

## Method notes

**Dispatch and arrival.** All 5 requests for a question are submitted at once, one thread each, in an order shuffled by `random.Random(dispatch_seed)`. Questions run one after another. A single lock-protected counter assigns `arrival_seq` when a response body has been fully read. The server ran with `OLLAMA_NUM_PARALLEL=1` (one request per model at a time) and `OLLAMA_MAX_LOADED_MODELS=0` (auto, 3 on this host). So requests to different models overlap, but at most 3 models are resident. The `/api/ps` samples record which models were loaded. Requests whose model is not loaded queue inside the server, so arrival order reflects real completion order: model speed, load time and queueing. It is not list order. The evaluator was occasionally run during collection, which adds a little CPU contention.

**seq.** In the Rust input, `seq = arrival_seq * 1000 + sentence index within the response`. For the original v1 responses no arrival times exist, so `seq = list position * 1000 + sentence index`. `../collect.py` queried the models one at a time in list order, so list order is also the original completion order.

**Same claims in both reducers.** The claims come from `../collect.py:extract_claims_from_text`. They then go through `evaluate_v2.load_contributions`, which applies the truncation filter and context-aware evidence association. The same dicts are fed to the Python reducer and lowered for Rust. The lowering is an identity map:

- polarity is `AFFIRM`;
- kind is `ASSERTION`;
- evidence `source` is the item's `text`;
- verification is `UNVERIFIED`;
- calibration is 0.7 for every agent, as in Python;
- criteria are empty, so constraint alignment is 1.0, as in Python.

**Policies, passed in the input JSON; the binary is unchanged.**

- `native` is the default policy.
- `forced` is the default policy with `values.incompatible_values` grouping every object of each predicate. This makes every (s, p) an exclusive slot, which is the Python harness's conflict structure, and is what Table A uses.
- `_rec0` sets the recency weight to 0.
- `_nodb` sets the deadband to 0, so Schulze never runs.
- `_evonly` sets the weights to [1,0,0,0,0] with deadband 0. The evidence value is recovered as the quantized score divided by the lowering factor.

**Equivalence ladder.** A Python mirror of `compiler.rs` P4/P5 for assertion-only inputs is checked against the binary on every run: winners, quantized scores, deadband flags and admitted sets. The mirror then moves from the Python reducer to Rust one step at a time:

- L1: LOW-lowering-confidence claims are excluded from detection and rejected (§6.4);
- L2: arity-aware slot keys;
- L3: Rust evidence math (verification quality 0.40, source reliability, cross-reference multiplier);
- L4: quantized strict-greater comparison;
- L5: deadband and Schulze.

Each disagreement is attributed to the first step that changes the output. Some causes are 0 by construction, because the inputs are identical on those dimensions:

- calibration (0.7 on both sides);
- critique (no critiques are lowered);
- polarity (no NEGATE forms);
- recency source (both sides use the same order).

**Scoring.** Both graders come from `evaluate_v2.py`. A set is eligible when some member matches gold, and decisive when some member does not.

- **Table A** uses the Python harness's contradiction sets. If Rust forms no slot because members were excluded as LOW, the set is "dissolved". A dissolved set counts as correct only if Rust admits at least one member and every admitted member matches gold.
- **Table B** uses the Rust-native contradiction slots.

For both tables, majority, first and last use member order, which is arrival order. McNemar is exact. The bootstrap resamples questions, 10,000 times, with seed 42.

**Do not fabricate.** No new questions or gold triples were added.
