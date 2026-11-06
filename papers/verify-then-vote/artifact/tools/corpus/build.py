"""Build the Swarm 3 retrieval corpora and their BM25 indexes (v3/SWARM3_DESIGN.md §2).

Two corpora, routed by item source:

  fever17  FEVER 2017 wiki-pages (Wikipedia lead sections), CC BY-SA 3.0
  scifact  SciFact corpus (5,183 abstracts), ODC-By 1.0

Pipeline (each step is deterministic and content-hashed):

  1. passages   source -> corpus-cache/<corpus>/passages.jsonl (+ passages.offsets.npy)
                ≤1,000-char chunks cut on sentence boundaries (chunker `bran-chunk/1`).
  2. index      passages.jsonl -> corpus-cache/<corpus>/index/ (a stock bm25s index,
                loadable with bm25s.BM25.load(mmap=True|False)).
  3. manifest   tools/corpus/corpus_manifest.json (source hashes, licence, tokenizer,
                parameters, versions, corpus_sha256, index_sha256).

The index builder streams token ids into flat numpy arrays instead of bm25s's
list-of-lists, so 5.4M passages fit in RAM. It reproduces bm25s 0.3.14's
`bm25s.tokenize(...)` + `BM25(method="lucene").index(...)` arithmetic exactly; the
test suite asserts byte-identical index files against the stock bm25s path.

Usage (run with tools/corpus/.venv/bin/python -I):

  build.py passages --corpus scifact
  build.py passages --corpus fever17 --zip corpus-cache/download/wiki-pages.zip
  build.py index    --corpus scifact [--out DIR]
  build.py manifest
"""

import argparse
import hashlib
import io
import json
import math
import os
import platform
import re
import sys
import time
import unicodedata
import zipfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
# Prefer the public name; the fallback reads historical launch configurations.
CACHE = Path(os.environ.get("OVERTURN_CORPUS_CACHE", os.environ.get("BRAN_CORPUS_CACHE", REPO / "corpus-cache")))
MANIFEST_PATH = HERE / "corpus_manifest.json"

sys.path.insert(0, str(REPO / "tools" / "evidence"))
from canonical import canonical_bytes, canonical_json, sha256_hex  # noqa: E402

CHUNKER_VERSION = "bran-chunk/1"
MAX_CHARS = 1000
INDEX_FORMAT = "bran-bm25-index/1"

# Tokenizer: bm25s.tokenize defaults minus the stemmer (design §2.3).
TOKEN_PATTERN = r"(?u)\b\w\w+\b"
BM25_PARAMS = {"k1": 1.2, "b": 0.75, "method": "lucene", "idf_method": "lucene",
               "dtype": "float32", "int_dtype": "int32"}

SCIFACT_DIR = REPO / "real-agent-eval/v4/benchmark/downloads/scifact"
FEVER_URL = "https://fever.ai/download/fever/wiki-pages.zip"

CORPORA = {
    "fever17": {
        "description": "FEVER 2017 Wikipedia dump (wiki-pages.zip): lead sections, sentence-split",
        "source_url": FEVER_URL,
        "license": "CC BY-SA 3.0 (Wikipedia; FEVER 2017 release, fever.ai) -- share-alike applies to passage text",
        "key_format": "fever17:<page_id>:<chunk>",
    },
    "scifact": {
        "description": "SciFact corpus.jsonl (Wadden et al. 2020): titles + abstracts, sentence-split",
        "source_url": "https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz",
        "license": "ODC-By 1.0 (SciFact corpus; abstracts from S2ORC)",
        "key_format": "scifact:<doc_id>:<chunk>",
    },
}

# FEVER/PTB escapes in page ids and sentence text.
_PTB = {"-LRB-": "(", "-RRB-": ")", "-LSB-": "[", "-RSB-": "]",
        "-LCB-": "{", "-RCB-": "}", "-COLON-": ":"}
_PTB_RE = re.compile("|".join(re.escape(k) for k in _PTB))


def unescape_ptb(s):
    return _PTB_RE.sub(lambda m: _PTB[m.group(0)], s)


def fever_title(page_id):
    return unescape_ptb(page_id.replace("_", " "))


# --------------------------------------------------------------------------- chunker

def _split_long(sentence, limit=MAX_CHARS):
    """Split one over-long sentence on whitespace into pieces of <= limit chars."""
    out = []
    s = sentence
    while len(s) > limit:
        cut = s.rfind(" ", 0, limit + 1)
        if cut <= 0:
            cut = limit
        out.append(s[:cut].rstrip())
        s = s[cut:].lstrip()
    if s:
        out.append(s)
    return out


def chunk_sentences(sentences, limit=MAX_CHARS):
    """bran-chunk/1. sentences: list of (sent_id, text). Returns [(first_id, last_id, text)].

    Greedy: consecutive sentences joined by one space while the chunk stays <= limit
    chars. A sentence longer than limit becomes its own chunks, split on whitespace.
    """
    chunks = []
    cur, first, last = "", None, None
    for sid, text in sentences:
        text = " ".join(text.split())
        if not text:
            continue
        if len(text) > limit:
            if cur:
                chunks.append((first, last, cur))
                cur, first, last = "", None, None
            for piece in _split_long(text, limit):
                chunks.append((sid, sid, piece))
            continue
        if cur and len(cur) + 1 + len(text) <= limit:
            cur += " " + text
            last = sid
        else:
            if cur:
                chunks.append((first, last, cur))
            cur, first, last = text, sid, sid
    if cur:
        chunks.append((first, last, cur))
    return chunks


def passage_content(title, text):
    """The string that is indexed, shown to agents and hashed: title, newline, text."""
    return f"{title}\n{text}"


def make_passage(corpus_id, page_id, chunk_no, title, first, last, text):
    return {
        "key": f"{corpus_id}:{page_id}:{chunk_no}",
        "page_id": page_id,
        "chunk": chunk_no,
        "title": title,
        "sent_ids": [first, last],
        "text": text,
    }


# --------------------------------------------------------------------------- sources

def iter_scifact(corpus_path):
    with open(corpus_path, "rb") as f:
        for line in f:
            doc = json.loads(line)
            page_id = str(doc["doc_id"])
            title = " ".join(doc["title"].split())
            sents = list(enumerate(doc["abstract"]))
            for n, (a, b, text) in enumerate(chunk_sentences(sents)):
                yield make_passage("scifact", page_id, n, title, a, b, text)


def _fever_sentences(lines_field):
    out = []
    for row in lines_field.split("\n"):
        if not row:
            continue
        parts = row.split("\t")
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        out.append((int(parts[0]), unescape_ptb(parts[1])))
    return out


def fever_members(zf):
    """wiki-pages/wiki-NNN.jsonl only; the zip also carries __MACOSX/._* resource forks."""
    return sorted(n for n in zf.namelist()
                  if n.startswith("wiki-pages/") and n.endswith(".jsonl")
                  and not n.split("/")[-1].startswith("._"))


def iter_fever(zip_path):
    """Members in sorted name order, lines in file order; pages with no text skipped."""
    with zipfile.ZipFile(zip_path) as zf:
        names = fever_members(zf)
        for name in names:
            with zf.open(name) as raw:
                for line in io.TextIOWrapper(raw, encoding="utf-8"):
                    page = json.loads(line)
                    page_id = page.get("id", "")
                    if not page_id or not page.get("text", "").strip():
                        continue
                    sents = _fever_sentences(page.get("lines", ""))
                    title = fever_title(page_id)
                    for n, (a, b, text) in enumerate(chunk_sentences(sents)):
                        yield make_passage("fever17", page_id, n, title, a, b, text)


def file_sha256(path, bufsize=1 << 22):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(bufsize)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def write_passages(passages, out_dir):
    """passages.jsonl (canonical JSON per line) + passages.offsets.npy (int64, n+1)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / "passages.jsonl.tmp"
    offsets = [0]
    seen = set()
    h = hashlib.sha256()
    pos = 0
    ktmp = out_dir / "passages.keys.txt.tmp"
    with open(tmp, "wb") as f, open(ktmp, "wb") as kf:
        for p in passages:
            if p["key"] in seen:
                raise ValueError(f"duplicate passage key {p['key']}")
            seen.add(p["key"])
            if "\n" in p["key"]:
                raise ValueError(f"newline in passage key {p['key']!r}")
            kf.write(p["key"].encode("utf-8") + b"\n")
            line = canonical_bytes(p) + b"\n"
            f.write(line)
            h.update(line)
            pos += len(line)
            offsets.append(pos)
    os.replace(tmp, out_dir / "passages.jsonl")
    os.replace(ktmp, out_dir / "passages.keys.txt")
    np.save(out_dir / "passages.offsets.npy", np.asarray(offsets, dtype=np.int64))
    return {"n_passages": len(offsets) - 1, "passages_sha256": h.hexdigest()}


def corpus_sha256(source_sha256, passages_sha256):
    return sha256_hex(canonical_bytes({
        "chunker": CHUNKER_VERSION, "max_chars": MAX_CHARS,
        "source_sha256": source_sha256, "passages_sha256": passages_sha256,
    }))


def iter_contents(passages_path):
    with open(passages_path, "rb") as f:
        for line in f:
            p = json.loads(line)
            yield passage_content(p["title"], p["text"])


# --------------------------------------------------------------------------- tokenizer + BM25

def stopwords_en():
    from bm25s.stopwords import STOPWORDS_EN
    return STOPWORDS_EN


def tokenizer_config():
    sw = stopwords_en()
    return {
        "name": "bm25s.tokenize",
        "lower": True,
        "token_pattern": TOKEN_PATTERN,
        "stopwords": "bm25s english (STOPWORDS_EN)",
        "stopwords_sha256": sha256_hex(canonical_bytes(list(sw))),
        "stemmer": None,
        "indexed_text": "title + '\\n' + text",
        "query_duplicates": "kept (bm25s semantics: a repeated query token counts twice)",
    }


def versions():
    import bm25s
    import scipy
    try:
        import orjson  # noqa: F401
        orj = True
    except ImportError:
        orj = False
    return {
        "python": platform.python_version(),
        "unicodedata": unicodedata.unidata_version,
        "bm25s": bm25s.__version__,
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "orjson_present": orj,
    }


def hashed_versions(v):
    """Versions that can change index bytes or tokens. Python patch level is excluded."""
    return {
        "python": ".".join(v["python"].split(".")[:2]),
        "unicodedata": v["unicodedata"],
        "bm25s": v["bm25s"],
        "numpy": v["numpy"],
        "scipy": v["scipy"],
        "orjson_present": v["orjson_present"],
    }


def tokenize_stream(contents, report_every=0):
    """Streaming twin of bm25s.tokenize(return_ids=True): first-appearance vocab ids."""
    split = re.compile(TOKEN_PATTERN).findall
    stop = set(stopwords_en())
    vocab = {}
    from array import array
    buf = array("i")
    lens = array("q")
    t0 = time.time()
    for n, text in enumerate(contents):
        ids = []
        for tok in split(text.lower()):
            if tok in stop:
                continue
            i = vocab.get(tok)
            if i is None:
                i = len(vocab)
                vocab[tok] = i
            ids.append(i)
        buf.extend(ids)
        lens.append(len(ids))
        if report_every and (n + 1) % report_every == 0:
            print(f"  tokenized {n + 1:,} passages, {len(buf):,} tokens, "
                  f"vocab {len(vocab):,}, {time.time() - t0:.0f}s", flush=True)
    return (np.frombuffer(buf, dtype=np.int32), np.frombuffer(lens, dtype=np.int64), vocab)


def bm25_arrays(tok, lens, n_vocab, k1, b, block_docs=500_000):
    """Exact replica of bm25s 0.3.14 build_index_from_ids (lucene, numpy CSC backend).

    bm25s per document: tf float32 from Counter; tfc = tf / (k1*((1-b)+b*l_d/l_avg) + tf)
    evaluated in float64 (np.float64 l_avg promotes); idf = float32(math.log(1+(N-df+.5)/(df+.5)));
    score = float32(idf * tfc). CSC sorted by (column, row) via argsort of col<<32|row.
    """
    n_docs = int(lens.shape[0])
    avg_doc_len = lens.mean()  # np.float64, same pairwise sum as np.array(list_of_int).mean()
    starts = np.zeros(n_docs + 1, dtype=np.int64)
    np.cumsum(lens, out=starts[1:])

    pd, pt, ptf = [], [], []
    for d0 in range(0, n_docs, block_docs):
        d1 = min(n_docs, d0 + block_docs)
        t = tok[starts[d0]:starts[d1]].astype(np.int64)
        d = np.repeat(np.arange(d0, d1, dtype=np.int64), lens[d0:d1])
        key = d * n_vocab + t
        uk, cnt = np.unique(key, return_counts=True)
        pd.append((uk // n_vocab).astype(np.int32))
        pt.append((uk % n_vocab).astype(np.int32))
        ptf.append(cnt.astype(np.int32))
        del t, d, key, uk, cnt
    pair_doc = np.concatenate(pd) if pd else np.zeros(0, np.int32)
    pair_tok = np.concatenate(pt) if pt else np.zeros(0, np.int32)
    pair_tf = np.concatenate(ptf) if ptf else np.zeros(0, np.int32)
    del pd, pt, ptf

    df = np.bincount(pair_tok, minlength=n_vocab)
    idf = np.zeros(n_vocab, dtype=np.float32)
    cache = {}
    for tid, f in enumerate(df.tolist()):
        if f:
            v = cache.get(f)
            if v is None:
                v = cache[f] = math.log(1 + (n_docs - f + 0.5) / (f + 0.5))
            idf[tid] = v

    denom_doc = k1 * ((1 - b) + (b * lens.astype(np.float64)) / avg_doc_len)  # float64, per doc
    scores = np.empty(pair_doc.shape[0], dtype=np.float32)
    step = 50_000_000
    for i in range(0, pair_doc.shape[0], step):
        j = i + step
        tf64 = pair_tf[i:j].astype(np.float32).astype(np.float64)
        tfc = tf64 / (denom_doc[pair_doc[i:j]] + tf64)
        scores[i:j] = idf[pair_tok[i:j]] * tfc
    del pair_tf, denom_doc

    col_counts = np.bincount(pair_tok, minlength=n_vocab)
    indptr = np.zeros(n_vocab + 1, dtype=np.int64)
    np.cumsum(col_counts, out=indptr[1:])
    # pairs are sorted by (doc, tok); a stable sort on tok yields (tok, doc) order,
    # identical to bm25s's argsort over unique keys col<<32|row.
    sorter = np.argsort(pair_tok, kind="stable")
    data = scores[sorter]
    del scores
    indices = pair_doc[sorter]
    return {"data": data, "indices": indices, "indptr": indptr, "num_docs": n_docs}


def save_bm25s(scores, vocab, out_dir):
    """Write a stock bm25s index directory via bm25s's own save()."""
    import bm25s
    m = bm25s.BM25(k1=BM25_PARAMS["k1"], b=BM25_PARAMS["b"], method=BM25_PARAMS["method"],
                   dtype=BM25_PARAMS["dtype"], int_dtype=BM25_PARAMS["int_dtype"])
    vocab = dict(vocab)
    if "" not in vocab:  # bm25s index(create_empty_token=True)
        vocab[""] = (max(vocab.values()) + 1) if vocab else 0
    m.scores = scores
    m.vocab_dict = vocab
    m.nonoccurrence_array = None
    out_dir.mkdir(parents=True, exist_ok=True)
    m.save(str(out_dir), show_progress=False)


def build_index_streaming(contents, out_dir, report_every=0):
    t0 = time.time()
    tok, lens, vocab = tokenize_stream(contents, report_every=report_every)
    t1 = time.time()
    scores = bm25_arrays(tok, lens, len(vocab), BM25_PARAMS["k1"], BM25_PARAMS["b"])
    del tok
    t2 = time.time()
    save_bm25s(scores, vocab, out_dir)
    t3 = time.time()
    return {"tokenize_s": round(t1 - t0, 1), "score_s": round(t2 - t1, 1),
            "save_s": round(t3 - t2, 1), "n_docs": int(lens.shape[0]),
            "n_tokens": int(lens.sum()), "n_vocab": len(vocab),
            "nnz": int(scores["indptr"][-1])}


def build_index_reference(contents, out_dir):
    """Stock bm25s path (for tests only: holds every token list in Python memory)."""
    import bm25s
    toks = bm25s.tokenize(list(contents), lower=True, token_pattern=TOKEN_PATTERN,
                          stopwords="english", stemmer=None, show_progress=False)
    m = bm25s.BM25(k1=BM25_PARAMS["k1"], b=BM25_PARAMS["b"], method=BM25_PARAMS["method"],
                   dtype=BM25_PARAMS["dtype"], int_dtype=BM25_PARAMS["int_dtype"])
    m.index(toks, show_progress=False)
    out_dir.mkdir(parents=True, exist_ok=True)
    m.save(str(out_dir), show_progress=False)


INDEX_FILES = ("data.csc.index.npy", "indices.csc.index.npy", "indptr.csc.index.npy",
               "params.index.json", "vocab.index.json")


def index_files_sha256(index_dir):
    return {name: file_sha256(index_dir / name) for name in INDEX_FILES}


def index_sha256(files, corpus_sha, vers):
    params = {k: (repr(v) if isinstance(v, float) else v) for k, v in BM25_PARAMS.items()}
    return sha256_hex(canonical_bytes({
        "format": INDEX_FORMAT,
        "files": files,
        "tokenizer": tokenizer_config(),
        "bm25": params,
        "versions": hashed_versions(vers),
        "corpus_sha256": corpus_sha,
    }))


# --------------------------------------------------------------------------- manifest

def load_manifest():
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"format": "bran-corpus-manifest/1", "corpora": {}}


def save_manifest(m):
    m["format"] = "bran-corpus-manifest/1"
    MANIFEST_PATH.write_text(json.dumps(m, indent=1, sort_keys=True, ensure_ascii=False) + "\n")


def cmd_passages(args):
    cid = args.corpus
    out_dir = CACHE / cid
    t0 = time.time()
    if cid == "scifact":
        src = SCIFACT_DIR / "extracted/data/corpus.jsonl"
        source = {"file": str(src.relative_to(REPO)), "sha256": file_sha256(src),
                  "archive": str((SCIFACT_DIR / "data.tar.gz").relative_to(REPO)),
                  "archive_sha256": file_sha256(SCIFACT_DIR / "data.tar.gz")}
        res = write_passages(iter_scifact(src), out_dir)
    elif cid == "fever17":
        zp = Path(args.zip)
        print(f"hashing {zp} ...", flush=True)
        source = {"file": "wiki-pages.zip", "sha256": file_sha256(zp),
                  "bytes": zp.stat().st_size}
        res = write_passages(iter_fever(zp), out_dir)
    else:
        raise SystemExit(f"unknown corpus {cid}")
    m = load_manifest()
    entry = m["corpora"].setdefault(cid, {})
    entry.update(CORPORA[cid])
    entry["source"] = source
    entry["chunker"] = {"version": CHUNKER_VERSION, "max_chars": MAX_CHARS,
                        "rule": "greedy sentence packing joined by ' '; sentence > max_chars "
                                "split on whitespace; whitespace collapsed; empty sentences dropped"
                                + ("; PTB escapes (-LRB- etc.) decoded; title = page_id with '_'->' '"
                                   if cid == "fever17" else "")}
    entry["passages"] = {"file": f"corpus-cache/{cid}/passages.jsonl", **res,
                         "offsets_sha256": file_sha256(out_dir / "passages.offsets.npy"),
                         "passages_bytes": (out_dir / "passages.jsonl").stat().st_size}
    entry["corpus_sha256"] = corpus_sha256(source["sha256"], res["passages_sha256"])
    entry["passages_build_s"] = round(time.time() - t0, 1)
    save_manifest(m)
    print(json.dumps({cid: entry}, indent=1))


def cmd_index(args):
    cid = args.corpus
    m = load_manifest()
    entry = m["corpora"][cid]
    pdir = CACHE / cid
    out_dir = Path(args.out) if args.out else pdir / "index"
    assert file_sha256(pdir / "passages.jsonl") == entry["passages"]["passages_sha256"], \
        "passages.jsonl does not match the manifest"
    t0 = time.time()
    stats = build_index_streaming(iter_contents(pdir / "passages.jsonl"), out_dir,
                                  report_every=args.report_every)
    build_s = round(time.time() - t0, 1)
    vers = versions()
    files = index_files_sha256(out_dir)
    ih = index_sha256(files, entry["corpus_sha256"], vers)
    result = {"dir": str(out_dir), "index_sha256": ih, "files": files,
              "bytes": sum((out_dir / f).stat().st_size for f in INDEX_FILES),
              "build_s": build_s, **stats}
    print(json.dumps(result, indent=1))
    if args.out:  # a rebuild elsewhere: report only
        return
    entry["index"] = {"dir": f"corpus-cache/{cid}/index", "format": INDEX_FORMAT,
                      "index_sha256": ih, "files": files, "bytes": result["bytes"],
                      "n_docs": stats["n_docs"], "n_tokens": stats["n_tokens"],
                      "n_vocab": stats["n_vocab"], "nnz": stats["nnz"], "build_s": build_s,
                      "timings_s": {k: stats[k] for k in ("tokenize_s", "score_s", "save_s")}}
    entry["tokenizer"] = tokenizer_config()
    entry["bm25"] = BM25_PARAMS
    m["versions"] = vers
    save_manifest(m)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("passages")
    p.add_argument("--corpus", required=True, choices=sorted(CORPORA))
    p.add_argument("--zip", default=str(CACHE / "download/wiki-pages.zip"))
    p.set_defaults(fn=cmd_passages)
    p = sub.add_parser("index")
    p.add_argument("--corpus", required=True, choices=sorted(CORPORA))
    p.add_argument("--out", default=None, help="build elsewhere and only print hashes")
    p.add_argument("--report-every", type=int, default=500_000)
    p.set_defaults(fn=cmd_index)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
