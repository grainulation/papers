"""Determinism tests for tools/corpus (v3/DESIGN.md §2.3).

Run:  tools/corpus/.venv/bin/python -I -m unittest discover -s tools/corpus/tests -v

Env:
  OVERTURN_CORPUS_FULL=1   also run the fever17 tests that need the built 5.4M-passage index
                       (rebuild-hash test there takes the full build time).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORPUS_DIR = HERE.parent
sys.path.insert(0, str(CORPUS_DIR))
os.environ.setdefault("DISABLE_TQDM", "1")

import build  # noqa: E402
import retrieve  # noqa: E402

PY = sys.executable
REPO = build.REPO
FULL = os.environ.get("OVERTURN_CORPUS_FULL") == "1"

# The built corpora (corpus-cache/) and the downloaded datasets are git-ignored. Tests that read them
# skip when they are absent; tools/corpus/README.md ("Build") makes them.
HAVE_SCIFACT_SRC = (build.SCIFACT_DIR / "extracted/data/corpus.jsonl").exists()
HAVE_SCIFACT_INDEX = all((build.CACHE / "scifact" / n).exists()
                         for n in ("passages.jsonl", "passages.keys.txt", "index/params.index.json"))
needs_scifact_src = unittest.skipUnless(
    HAVE_SCIFACT_SRC, "needs the SciFact download in real-agent-eval/v4/benchmark/downloads/scifact (not distributed; see DATA_LICENSES.md)")
needs_scifact_index = unittest.skipUnless(
    HAVE_SCIFACT_INDEX, "needs the built SciFact corpus in corpus-cache/scifact or $OVERTURN_CORPUS_CACHE/scifact "
                        "(git-ignored; build it with tools/corpus/build.py)")


def scifact_queries(n=1000):
    d = build.SCIFACT_DIR / "extracted/data"
    out = []
    for name in ("claims_train.jsonl", "claims_dev.jsonl", "claims_test.jsonl"):
        with open(d / name) as f:
            out += [json.loads(line)["claim"] for line in f]
    return out[:n]


def fever_queries(n=1000):
    p = REPO / "real-agent-eval/v4/benchmark/downloads/fever/paper_dev.jsonl"
    out = []
    with open(p) as f:
        for line in f:
            out.append(json.loads(line)["claim"])
            if len(out) == n:
                break
    return out


def make_corpus(tmp, corpus_id, passages):
    """Build a throwaway corpus (passages + index + manifest entry) under tmp."""
    tmp = Path(tmp)
    res = build.write_passages(passages, tmp / corpus_id)
    stats = build.build_index_streaming(
        build.iter_contents(tmp / corpus_id / "passages.jsonl"), tmp / corpus_id / "index")
    files = build.index_files_sha256(tmp / corpus_id / "index")
    csha = build.corpus_sha256("test", res["passages_sha256"])
    ih = build.index_sha256(files, csha, build.versions())
    manifest = {"corpora": {corpus_id: {"corpus_sha256": csha,
                                        "index": {"index_sha256": ih, "files": files}}}}
    return manifest, stats


def P(cid, page, title, text, chunk=0):
    return build.make_passage(cid, page, chunk, title, 0, 0, text)


class TestChunker(unittest.TestCase):
    def test_limits_and_ids(self):
        sents = [(i, ("word%d " % i) * 30) for i in range(20)]
        chunks = build.chunk_sentences(sents)
        self.assertTrue(all(len(t) <= build.MAX_CHARS for _, _, t in chunks))
        ids = [i for a, b, _ in chunks for i in range(a, b + 1)]
        self.assertEqual(ids, list(range(20)))  # contiguous, each sentence once

    def test_long_sentence_split(self):
        long = " ".join(["x" * 9] * 300)  # 2,999 chars
        chunks = build.chunk_sentences([(0, "short."), (1, long), (2, "tail.")])
        self.assertEqual(chunks[0], (0, 0, "short."))
        self.assertEqual(chunks[-1], (2, 2, "tail."))
        mids = chunks[1:-1]
        self.assertTrue(all(a == b == 1 and len(t) <= build.MAX_CHARS for a, b, t in mids))
        self.assertEqual(" ".join(t for _, _, t in mids), long)

    def test_unbroken_token(self):
        chunks = build.chunk_sentences([(0, "y" * 2500)])
        self.assertEqual([len(t) for _, _, t in chunks], [1000, 1000, 500])

    def test_fever_lines_parse(self):
        lines = "0\tThe -LRB-film-RRB- is good .\tFilm\n1\t\n2\tSecond one .\tX\tY\n"
        self.assertEqual(build._fever_sentences(lines),
                         [(0, "The (film) is good ."), (1, ""), (2, "Second one .")])
        self.assertEqual(build.fever_title("Star_Wars_-LRB-film-RRB-"), "Star Wars (film)")

    @needs_scifact_src
    def test_scifact_passages_deterministic(self):
        src = build.SCIFACT_DIR / "extracted/data/corpus.jsonl"
        a = [build.canonical_bytes(p) for p in build.iter_scifact(src)]
        b = [build.canonical_bytes(p) for p in build.iter_scifact(src)]
        self.assertEqual(a, b)
        m = build.load_manifest()["corpora"]["scifact"]
        self.assertEqual(build.sha256_hex(b"".join(x + b"\n" for x in a)),
                         m["passages"]["passages_sha256"])


class TestBuilderMatchesStockBm25s(unittest.TestCase):
    """The streaming builder must write the same bytes as bm25s.tokenize + BM25.index."""

    def _compare(self, contents):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "stream", Path(tmp) / "stock"
            build.build_index_streaming(iter(contents), a)
            build.build_index_reference(contents, b)
            for name in build.INDEX_FILES:
                self.assertEqual((a / name).read_bytes(), (b / name).read_bytes(), name)

    def test_synthetic_edge_cases(self):
        self._compare([
            "the a an of",                      # stopwords only -> empty doc
            "Alpha beta beta BETA gamma",       # repeated terms, case folding
            "",                                 # empty
            "x y z single letters dropped",     # \w\w+ drops 1-char tokens
            "Ünïcode naïve café 東京 tokyo",       # unicode \w
            "alpha " * 200,                     # long doc, tf=200
            "gamma delta 1999 1999-2000",
        ])

    @needs_scifact_index
    def test_scifact_full(self):
        contents = list(build.iter_contents(build.CACHE / "scifact/passages.jsonl"))
        self._compare(contents)


class TestIndexIdentity(unittest.TestCase):
    @needs_scifact_src
    @needs_scifact_index
    def test_scifact_rebuild_same_hash_and_results(self):
        m = build.load_manifest()
        entry = m["corpora"]["scifact"]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "index"
            build.build_index_streaming(build.iter_contents(build.CACHE / "scifact/passages.jsonl"), out)
            files = build.index_files_sha256(out)
            self.assertEqual(files, entry["index"]["files"])
            self.assertEqual(build.index_sha256(files, entry["corpus_sha256"], build.versions()),
                             entry["index"]["index_sha256"])
            orig = retrieve.Corpus("scifact")
            rebuilt = retrieve.Corpus("scifact", index_dir=out)
            for q in scifact_queries(1000):
                self.assertEqual(retrieve.retrieve(q, orig, 10), retrieve.retrieve(q, rebuilt, 10), q)

    @needs_scifact_index
    def test_manifest_files_match_disk(self):
        for cid, entry in build.load_manifest()["corpora"].items():
            if "index" not in entry or (cid == "fever17" and not FULL):
                continue
            self.assertEqual(build.index_files_sha256(build.CACHE / cid / "index"),
                             entry["index"]["files"], cid)

    def test_hash_sensitivity(self):
        m = build.load_manifest()["corpora"]["scifact"]
        v = build.versions()
        base = build.index_sha256(m["index"]["files"], m["corpus_sha256"], v)
        self.assertNotEqual(base, build.index_sha256(m["index"]["files"], "0" * 64, v))
        self.assertNotEqual(base, build.index_sha256(m["index"]["files"], m["corpus_sha256"],
                                                     {**v, "bm25s": "0.0.0"}))
        files = dict(m["index"]["files"], **{"data.csc.index.npy": "0" * 64})
        self.assertNotEqual(base, build.index_sha256(files, m["corpus_sha256"], v))


DUMP = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import retrieve, build
corpus, n, mode = sys.argv[2], int(sys.argv[3]), sys.argv[4]
qs = json.loads(sys.stdin.read())[:n]
c = retrieve.Corpus(corpus, mmap_index=(mode == "mmap"))
for q in qs:
    sys.stdout.write(build.canonical_json(retrieve.retrieve(q, c, 10)) + "\n")
"""


@needs_scifact_index
class TestRecordDeterminism(unittest.TestCase):
    def _dump(self, corpus, queries, seed, mode="mmap"):
        env = dict(os.environ, PYTHONHASHSEED=str(seed), DISABLE_TQDM="1")
        r = subprocess.run([PY, "-I", "-c", DUMP, str(CORPUS_DIR), corpus, str(len(queries)), mode],
                           input=json.dumps(queries).encode(), capture_output=True, env=env, check=True)
        return r.stdout

    def _cross_process(self, corpus, queries):
        a = self._dump(corpus, queries, 1)
        b = self._dump(corpus, queries, 987654, mode="mmap")
        c = self._dump(corpus, queries, 42, mode="eager")
        self.assertEqual(a, b, "same query, different process/hash seed")
        self.assertEqual(a, c, "mmap vs eager")
        self.assertEqual(len(a.splitlines()), len(queries))

    @needs_scifact_src
    def test_scifact_cross_process_and_mmap(self):
        self._cross_process("scifact", scifact_queries(300))

    @unittest.skipUnless(FULL, "needs fever17 index (OVERTURN_CORPUS_FULL=1)")
    def test_fever_cross_process_and_mmap(self):
        self._cross_process("fever17", fever_queries(200))

    def test_in_process_repeat_and_seal(self):
        c = retrieve.Corpus("scifact")
        q = "Vitamin D deficiency increases the risk of multiple sclerosis."
        r1 = retrieve.retrieve(q, c, 5)
        r2 = retrieve.retrieve(q, retrieve.Corpus("scifact", mmap_index=False), 5)
        self.assertEqual(build.canonical_bytes(r1), build.canonical_bytes(r2))
        self.assertEqual(r1["schema"], "bran-retrieval/1")
        self.assertEqual(set(r1), {"schema", "query", "corpus_id", "index_sha256", "k",
                                   "results", "retrieval_sha256"})
        self.assertTrue(retrieve.verify_record(r1))
        tampered = json.loads(json.dumps(r1))
        tampered["results"][0]["score_q"] += 1
        self.assertFalse(retrieve.verify_record(tampered))
        for r in r1["results"]:
            self.assertIsInstance(r["score_q"], int)

    def test_edge_queries(self):
        c = retrieve.Corpus("scifact")
        self.assertEqual(retrieve.retrieve("", c, 3)["results"], [])
        self.assertEqual(retrieve.retrieve("the of and", c, 3)["results"], [])
        self.assertEqual(retrieve.retrieve("zzqqxxnotaword", c, 3)["results"], [])
        for bad in (0, 51, 2.0, True):
            with self.assertRaises(retrieve.RetrievalError):
                retrieve.retrieve("cancer", c, bad)

    def test_get_passage(self):
        r = retrieve.retrieve("multiple sclerosis vitamin D", "scifact", 1)
        p = retrieve.get_passage(r["results"][0]["passage_key"])
        self.assertEqual(p["key"], r["results"][0]["passage_key"])
        self.assertEqual(p["content"], p["title"] + "\n" + p["text"])
        self.assertIsNone(retrieve.get_passage("scifact:nope:0"))


class TestTieBreak(unittest.TestCase):
    """Equal score_q must be ordered by passage_key, whatever the index order."""

    def _results(self, passages, query, k):
        with tempfile.TemporaryDirectory() as tmp:
            manifest, _ = make_corpus(tmp, "tie", passages)
            c = retrieve.Corpus("tie", cache=tmp, manifest=manifest)
            return retrieve.retrieve(query, c, k)["results"]

    def test_identical_passages_any_order(self):
        keys = ["b", "a", "c:x", "a:b", "aa", "Z", "é"]  # page ids; ':' allowed in page ids
        filler = [P("tie", f"f{i}", f"filler {i}", f"unrelated words number {i}") for i in range(20)]
        same = [P("tie", k, "Same", "orbital resonance of moons") for k in keys]
        r1 = self._results(same + filler, "orbital resonance", 5)
        r2 = self._results(filler + same[::-1], "orbital resonance", 5)
        self.assertEqual(r1, r2)
        self.assertEqual(len({x["score_q"] for x in r1}), 1)
        want = sorted(f"tie:{k}:0" for k in keys)[:5]
        self.assertEqual([x["passage_key"] for x in r1], want)

    def test_cut_falls_inside_a_tie(self):
        # 1 strong passage + 6 tied ones; k=3 must take the two smallest keys of the tie.
        strong = P("tie", "s", "Strong", "orbital orbital orbital resonance resonance")
        tied = [P("tie", f"t{i}", "Tied", "orbital resonance") for i in (5, 3, 9, 1, 7, 2)]
        filler = [P("tie", f"f{i}", "f", f"noise {i}") for i in range(10)]
        r = self._results(tied + [strong] + filler, "orbital resonance", 3)
        self.assertEqual([x["passage_key"] for x in r], ["tie:s:0", "tie:t1:0", "tie:t2:0"])
        r_rev = self._results(filler + [strong] + tied[::-1], "orbital resonance", 3)
        self.assertEqual(r, r_rev)

    def test_quantization_merges_near_ties(self):
        # Float order (m3 > m1 > m2) is overridden: all three quantize to 1000, so the
        # passage key decides. A float top-k cut would have dropped m1 at k=1.
        passages = [P("tie", k, "x", "photon") for k in ("m3", "m1", "m2", "m4")]
        with tempfile.TemporaryDirectory() as tmp:
            manifest, _ = make_corpus(tmp, "tie", passages)
            c = retrieve.Corpus("tie", cache=tmp, manifest=manifest)
            import numpy as np
            fake = np.array([1.0004, 1.0001, 0.9996, 0.9994], dtype=np.float32)
            c.bm25.get_scores_from_ids = lambda ids: fake
            r1 = retrieve.retrieve("photon", c, 1)["results"]
            r3 = retrieve.retrieve("photon", c, 3)["results"]
            c.close()
        self.assertEqual(r1, [{"passage_key": "tie:m1:0", "score_q": 1000}])
        self.assertEqual([x["passage_key"] for x in r3], ["tie:m1:0", "tie:m2:0", "tie:m3:0"])
        self.assertEqual(round(1000 * float(np.float32(0.9994))), 999)


@unittest.skipUnless(FULL, "needs fever17 index (OVERTURN_CORPUS_FULL=1)")
class TestFeverRebuild(unittest.TestCase):
    def test_rebuild_same_hash_and_1000_queries(self):
        entry = build.load_manifest()["corpora"]["fever17"]
        tmp = Path(tempfile.mkdtemp(dir=build.CACHE))
        try:
            out = tmp / "index"
            build.build_index_streaming(build.iter_contents(build.CACHE / "fever17/passages.jsonl"), out)
            files = build.index_files_sha256(out)
            self.assertEqual(files, entry["index"]["files"])
            orig = retrieve.Corpus("fever17")
            rebuilt = retrieve.Corpus("fever17", index_dir=out)
            for q in fever_queries(1000):
                self.assertEqual(retrieve.retrieve(q, orig, 10), retrieve.retrieve(q, rebuilt, 10), q)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
