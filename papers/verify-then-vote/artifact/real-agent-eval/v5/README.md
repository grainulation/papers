# Eval v5: grounded agents (harness)

Spec: `v3/DESIGN.md` §3 (agent protocol), §7 and §8. Items: `benchmark/`.
Retrieval: `tools/corpus/`. This directory's harness is `collect_v5.py`; its prompts
are in `prompts/` and its JSON schemas in `schema/`.

## Run

The harness needs bm25s and numpy, so it runs under the corpus venv:

```sh
PY="tools/corpus/.venv/bin/python -I"
$PY real-agent-eval/v5/collect_v5.py build-dense                      # once: SciFact dense index
$PY real-agent-eval/v5/collect_v5.py --split dev                      # dev, all 160 items
$PY real-agent-eval/v5/collect_v5.py --split dev --ids <ids> --out real-agent-eval/v5/results/pilot
$PY real-agent-eval/v5/collect_v5.py audit --out real-agent-eval/v5/results/pilot
$PY real-agent-eval/v5/collect_v5.py --split conf --n-items I         # only after the freeze
```

Run nothing else on Ollama meanwhile (`pgrep -f collect_v4.py` empty), as in v4.

## Protocol (design §3)

Same five models and digests as v4 (checked against `v3/results/run_manifest.json`), temperature
0.7, seed 42, dispatch seed 20261101 (one shuffle per item of the full split file, as v4).
`num_ctx` is set to 4096 for both turns (v4 left it at the server default).

Per item, the five agents are dispatched concurrently in the shuffled order; each agent thread runs:

1. **Query turn.** `prompts/query_v5.txt`: the question or claim only; multiple-choice options
   are never shown. Output is constrained by `schema/query_v5.schema.json` (`{"query"}`),
   `num_predict` 32. The query used is the first 12 words of the parsed `query`; a truncated JSON
   string is recovered by a partial parse; an empty or failed turn falls back to the question text
   (`query_source = fallback_question`, gold-blind and audited).
2. **Retrieval.** The agent's own query, k = 5, labelled P1–P5 by rank.
   - fever17 items (TQA, PopQA, FEVER): BM25, `tools/corpus/retrieve.py`, a sealed
     `bran-retrieval/1` record.
   - SciFact items: BM25 or dense `nomic-embed-text`, by the seeded rule
     `random.Random("v5-ret:"+id)`: shuffle the 5 models, the first 2 or 3 (coin flip) are dense,
     so each model is dense on half of the items in expectation (§3.2). Dense records use the
     same `bran-retrieval/1` fields; their `index_sha256` names the dense index
     (`corpus-cache/scifact_dense/dense_manifest.json`, format `bran-dense-index/1`), and the raw
     record also stores the query embedding (float32, base64) and its sha256.
3. **Answer turn.** `prompts/answer_v5.txt`: question, options and the agent's passages
   (neutralised as in the support checker, between `<<<PASSAGES` / `PASSAGES>>>`). Output is
   constrained by `schema/answer_v5.schema.json` with `answer` = the item's `answer_schema`
   (PopQA adds `minLength: 1`) and `citations.items.enum` = the labels actually shown, at most 3.
   A citation can therefore only name one of the agent's own passages. `num_predict` 512.

**Mixed-fleet arm** (`--mixed-fleet`, pre-declared fallback, §3.2; not used unless the dev gate
fails): on each item 2 of 5 agents are closed-book (no query turn, no passages, `citations`
maxItems 0), the pair chosen by `random.Random("v5-cb:"+id)` from the 10 model pairs.

## Raw records

`results/<split>/raw/<id>.json` (`bran-v5-raw/1`), one per item:

- `item_view` (whitelisted agent-visible fields only) and its sha256. No gold-bearing field
  (benchmark README) is read into any prompt or record.
- `dispatch_order`, `arrival_order`, `retriever_assignment`, `closed_book_models`,
  `retrieval_record_ids` (model → `retrieval_sha256`), `item_wall_s`, `/api/ps` samples.
- Per agent: `query_turn` and `answer_turn` (rendered prompt, `prompt_sha256`, `format_sha256`,
  options, raw response, Ollama timing metadata, attempts, timestamps; `query_arrival_seq` /
  `arrival_seq`), `retrieval` (the full sealed record, `record_verified`, shown passages with
  `passage_key` and `content_sha256` of `title + "\n" + text`), `parsed`.
- `arrival_seq` comes from one process-wide sequencer at the answer turn's body read; the query
  turns have their own counter.

`results/<split>/run_manifest.json` records each session: Ollama version and server env, model
digests (and the embedder's), prompt/schema/harness hashes, corpus and index hashes, the dense
manifest, options, seeds, freeze status.

## Parse audit

`collect_v5.py audit --out DIR` writes `DIR/parse_audit.json` from the raw records only (no gold):
per model the parse status (`ok`, `ok_with_violations`, `schema_violation`, `json_error`,
`truncated`, `request_error`), truncations, citation validity (cited labels that were shown),
query-turn sources; per item the wall time and the number of distinct (normalised) answers.

## Freeze guard

If `FREEZE.json` exists, every file it lists (`{"sha256": {repo-relative path: sha256}}`) must
match. `--split conf` refuses to run unless `FREEZE.json` exists and lists every file in
`CONF_FROZEN` (harness, prompts, schemas, confirmatory items, corpus manifest, `retrieve.py`,
`build.py`, dense manifest); on conf the index files are also re-hashed against the corpus
manifest.
