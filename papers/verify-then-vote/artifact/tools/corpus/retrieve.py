"""Deterministic BM25 retrieval sealed as `bran-retrieval/1` (v3/SWARM3_DESIGN.md §2.3).

    from retrieve import retrieve, get_passage
    rec = retrieve("who wrote the iliad", "fever17", k=5)

Record (canonical JSON, tools/evidence/canonical.py):

    {"corpus_id", "index_sha256", "k", "query",
     "results": [{"passage_key", "score_q"}, ...],
     "schema": "bran-retrieval/1",
     "retrieval_sha256": sha256(canonical_bytes(record without retrieval_sha256))}

Ranking (a total order, so the record is a pure function of (query, index)):

  1. tokens = bm25s tokenizer (lower, regex, english stopwords, no stemmer); OOV dropped.
  2. scores = bm25s get_scores (float32, accumulated in query-token order).
  3. score_q = round_half_even(1000 * float64(score)) for every passage; score_q <= 0 dropped.
  4. order by (-score_q, passage_key as UTF-8 bytes); keep the first k (1 <= k <= 50).

Quantizing before selecting differs from the design text ("top 50 by float, then quantize"):
a float top-50 cut can split passages whose score_q is equal, making the result depend on
float noise and argpartition tie handling. Here the cut is taken on score_q, so every
passage tied at the k-th score_q competes on passage_key.
"""

import json
import mmap
import os
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build  # noqa: E402
from build import canonical_bytes, sha256_hex  # noqa: E402

SCHEMA = "bran-retrieval/1"
K_MAX = 50

_LOADED = {}


class RetrievalError(ValueError):
    pass


class Corpus:
    """One loaded corpus: bm25s index (mmap or eager) + passage store (mmap)."""

    def __init__(self, corpus_id, cache=None, index_dir=None, mmap_index=True,
                 manifest=None, verify=False):
        import bm25s
        cache = Path(cache) if cache else build.CACHE
        manifest = manifest if manifest is not None else build.load_manifest()
        entry = manifest["corpora"].get(corpus_id)
        if not entry or "index" not in entry:
            raise RetrievalError(f"corpus {corpus_id!r} has no index in the manifest")
        self.corpus_id = corpus_id
        self.index_sha256 = entry["index"]["index_sha256"]
        self.index_dir = Path(index_dir) if index_dir else cache / corpus_id / "index"
        if verify:
            files = build.index_files_sha256(self.index_dir)
            if files != entry["index"]["files"]:
                raise RetrievalError(f"{self.index_dir} does not match the manifest")
        self.bm25 = bm25s.BM25.load(str(self.index_dir), mmap=mmap_index,
                                    show_progress=False, verbosity=0)
        self.vocab = self.bm25.vocab_dict
        self.n_index_vocab = len(self.bm25.scores["indptr"]) - 1
        pdir = self._pdir = cache / corpus_id
        self._offsets = np.load(pdir / "passages.offsets.npy", mmap_mode="r")
        self._fh = open(pdir / "passages.jsonl", "rb")
        self._mm = mmap.mmap(self._fh.fileno(), 0, access=mmap.ACCESS_READ)
        if len(self._offsets) - 1 != self.bm25.scores["num_docs"]:
            raise RetrievalError("passage store and index disagree on passage count")
        self._split = re.compile(build.TOKEN_PATTERN).findall
        self._stop = set(build.stopwords_en())

    def passage(self, i):
        a, b = int(self._offsets[i]), int(self._offsets[i + 1])
        return json.loads(self._mm[a:b])

    def close(self):
        self._mm.close()
        self._fh.close()

    def key_index(self):
        """passage_key -> row, from passages.keys.txt (built lazily, once per process)."""
        if getattr(self, "_keys", None) is None:
            raw = (self._pdir / "passages.keys.txt").read_bytes().decode("utf-8")
            self._keys = {key: i for i, key in enumerate(raw.split("\n")[:-1])}
        return self._keys

    def passage_key(self, i):
        return self.passage(i)["key"]

    def query_ids(self, query):
        ids = []
        for tok in self._split(query.lower()):
            if tok in self._stop:
                continue
            tid = self.vocab.get(tok)
            if tid is not None and tid < self.n_index_vocab:
                ids.append(tid)
        return ids

    def rank(self, query, k):
        ids = self.query_ids(query)
        if not ids:
            return []
        scores = self.bm25.get_scores_from_ids(ids)
        q = np.rint(scores.astype(np.float64) * 1000.0).astype(np.int64)
        pos = np.flatnonzero(q > 0)
        if pos.size == 0:
            return []
        qv = q[pos]
        if pos.size > k:
            kth = np.partition(qv, pos.size - k)[pos.size - k]  # k-th largest score_q
            keep = qv >= kth
            pos, qv = pos[keep], qv[keep]
        cand = [(-int(s), self.passage_key(int(i)).encode("utf-8")) for i, s in zip(pos, qv)]
        cand.sort()
        return [{"passage_key": key.decode("utf-8"), "score_q": -neg} for neg, key in cand[:k]]


def load(corpus_id, **kw):
    key = (corpus_id, kw.get("index_dir"), kw.get("mmap_index", True))
    if key not in _LOADED:
        _LOADED[key] = Corpus(corpus_id, **kw)
    return _LOADED[key]


def seal(record):
    body = {k: v for k, v in record.items() if k != "retrieval_sha256"}
    return {**body, "retrieval_sha256": sha256_hex(canonical_bytes(body))}


def verify_record(record):
    return seal(record)["retrieval_sha256"] == record.get("retrieval_sha256")


def retrieve(query, corpus, k=5, **load_kw):
    """Top-k passages of `corpus` ("fever17" | "scifact") for `query`, sealed bran-retrieval/1."""
    if not isinstance(query, str):
        raise RetrievalError("query must be a string")
    if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= K_MAX:
        raise RetrievalError(f"k must be an int in 1..{K_MAX}")
    c = corpus if isinstance(corpus, Corpus) else load(corpus, **load_kw)
    return seal({
        "schema": SCHEMA,
        "query": query,
        "corpus_id": c.corpus_id,
        "index_sha256": c.index_sha256,
        "k": k,
        "results": c.rank(query, k),
    })


def get_passage(passage_key, **load_kw):
    """Passage record for a key `<corpus_id>:<page_id>:<chunk>` (page ids may contain ':').

    Returns the stored passage plus `content` (title + '\\n' + text, the indexed string).
    """
    corpus_id = passage_key.split(":", 1)[0]
    c = load(corpus_id, **load_kw)
    idx = c.key_index().get(passage_key)
    if idx is None:
        return None
    p = c.passage(idx)
    p["content"] = build.passage_content(p["title"], p["text"])
    return p




def main(argv=None):
    import argparse
    import time
    ap = argparse.ArgumentParser(description="bran-retrieval/1 query")
    ap.add_argument("corpus")
    ap.add_argument("query")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--eager", action="store_true")
    ap.add_argument("--show", action="store_true", help="print passage text too")
    a = ap.parse_args(argv)
    t0 = time.time()
    c = load(a.corpus, mmap_index=not a.eager)
    t1 = time.time()
    rec = retrieve(a.query, c, a.k)
    t2 = time.time()
    print(build.canonical_json(rec))
    print(f"load {t1 - t0:.2f}s query {1000 * (t2 - t1):.1f}ms", file=sys.stderr)
    if a.show:
        for r in rec["results"]:
            p = get_passage(r["passage_key"], mmap_index=not a.eager)
            print(f"--- {r['passage_key']} {r['score_q']}\n{p['content']}", file=sys.stderr)


if __name__ == "__main__":
    os.environ.setdefault("DISABLE_TQDM", "1")
    main()
