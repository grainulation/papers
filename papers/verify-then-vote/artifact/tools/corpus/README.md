# tools/corpus — retrieval corpora

Spec: `v3/DESIGN.md` §2. Two corpora, routed by item source (gold-blind):

| corpus_id | source | licence | passages |
|---|---|---|---|
| `fever17` | FEVER 2017 `wiki-pages.zip` (Wikipedia lead sections) | CC BY-SA 3.0 | see `corpus_manifest.json` |
| `scifact` | SciFact `corpus.jsonl` (v4 download) | ODC-By 1.0 | 10,107 |

Everything large lives in the git-ignored `corpus-cache/` at the repo root. Only
`corpus_manifest.json` (hashes, licence, tokenizer, parameters, versions) is committed.

## Setup

```sh
python3.12 -m venv tools/corpus/.venv
tools/corpus/.venv/bin/pip install bm25s==0.3.14 numpy==2.5.4 scipy==1.18.1
```

## Build

```sh
PY="nice -n 10 tools/corpus/.venv/bin/python -I"
curl -o corpus-cache/download/wiki-pages.zip https://fever.ai/download/fever/wiki-pages.zip
$PY tools/corpus/build.py passages --corpus fever17   # streams the zip; zip can be deleted after
$PY tools/corpus/build.py passages --corpus scifact
$PY tools/corpus/build.py index --corpus fever17
$PY tools/corpus/build.py index --corpus scifact
$PY tools/corpus/build.py index --corpus fever17 --out /elsewhere   # rebuild check: prints hashes only
```

`corpus-cache/<corpus>/` then holds `passages.jsonl` (one canonical-JSON passage per line),
`passages.offsets.npy`, `passages.keys.txt` and `index/` (a stock bm25s index directory).

## Passages (`bran-chunk/1`)

- Key `<corpus_id>:<page_id>:<chunk>`. FEVER page ids can contain `:`; split a key with
  `key.split(":", 1)` for the corpus and `rsplit(":", 1)` for the chunk.
- Fields: `key, page_id, chunk, title, sent_ids [first, last], text`. `sent_ids` are the
  dump's sentence ids, so FEVER gold `(page, sent_id)` maps to passage keys.
- Chunking: consecutive sentences joined by one space while ≤ 1,000 chars; an over-long
  sentence is split on whitespace. Whitespace collapsed, empty sentences dropped.
- FEVER: PTB escapes (`-LRB-` → `(` etc.) decoded in text and title; title = page id with
  `_` → space; pages with empty text skipped. Members read in sorted name order.
- **Indexed/displayed content = `title + "\n" + text`** (`build.passage_content`). Corpus capture should
  hash this string as the passage's `content_sha256`; `retrieve.get_passage` returns it.

## Index

- bm25s 0.3.14, `method="lucene"`, k1 = 1.2, b = 0.75, float32 scores, int32 indices.
- Tokenizer: bm25s rules — lowercase, `(?u)\b\w\w+\b`, bm25s English stopwords, no stemmer.
- `build.py` streams token ids into flat numpy arrays rather than bm25s's per-document
  Python lists (which would not fit 5.4M passages in RAM) and reproduces bm25s's arithmetic
  exactly; the tests assert **byte-identical index files** against stock
  `bm25s.tokenize` + `BM25.index` on SciFact and on synthetic edge cases. Files are written
  by bm25s's own `save()`, and retrieval loads them with `bm25s.BM25.load`.
- `index_sha256 = sha256(canonical_json({format, files: {name: sha256}, tokenizer, bm25,
  versions, corpus_sha256}))`, where `corpus_sha256 = sha256(canonical_json({chunker,
  max_chars, source_sha256, passages_sha256}))`. Versions hashed: python major.minor,
  unicodedata version (it governs `\w` and `lower()`), bm25s, numpy, scipy, orjson presence
  (bm25s writes the vocab with orjson when installed, which changes its bytes).

## Retrieval (`bran-retrieval/1`)

```python
sys.path.insert(0, "tools/corpus"); from retrieve import retrieve, get_passage, verify_record
rec = retrieve("Nikolaj Coster-Waldau worked with Fox.", "fever17", k=5)
```

```json
{"corpus_id":"fever17","index_sha256":"…","k":5,"query":"…",
 "results":[{"passage_key":"fever17:…:0","score_q":23125}, …],
 "retrieval_sha256":"…","schema":"bran-retrieval/1"}
```

- `score_q = round_half_even(1000 · float64(bm25 float32 score))`; passages with
  `score_q ≤ 0` are dropped; order is `(−score_q, passage_key UTF-8 bytes)`; `1 ≤ k ≤ 50`.
- Quantization happens **before** the cut, over every passage, so ties at the k-th place are
  settled by key. (The design text cut the float top 50 first; see "Design deviations".)
- `retrieval_sha256` = sha256 of the canonical JSON of the record without that field
  (`tools/evidence/canonical.py`). `verify_record` rechecks it.
- Repeated query tokens count twice (bm25s semantics). OOV tokens are dropped; a query with
  no in-vocabulary tokens returns `results: []`.

## Tests

```sh
tools/corpus/.venv/bin/python -I -m unittest discover -s tools/corpus/tests -v
OVERTURN_CORPUS_FULL=1 nice -n 10 tools/corpus/.venv/bin/python -I -m unittest discover -s tools/corpus/tests -v
```

Covers: chunker limits and determinism; streaming builder byte-identical to stock bm25s;
rebuild → same file hashes, same `index_sha256`, same records on 1,000 fixed queries
(SciFact claims; FEVER `paper_dev` claims with `OVERTURN_CORPUS_FULL=1`); same query →
byte-identical record across processes with different `PYTHONHASHSEED`; mmap vs eager
loading; seal/tamper; tie-break by key regardless of index order, including a cut that
falls inside a tie and float near-ties merged by quantization.

## Design deviations

See `corpus_manifest.json` → `notes`.

## Runtime configuration

Set `OVERTURN_CORPUS_CACHE` to use a corpus cache outside `corpus-cache/`. The historical `BRAN_CORPUS_CACHE` variable is read only as a compatibility fallback when the public variable is unset. Serialized format identifiers remain unchanged so existing corpus manifests and sealed records verify.
