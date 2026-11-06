"""Local-corpus capture tests (v3/evidence-corpus-addendum.md, design §2.4).

Every test runs under NoNetwork, and the corpus is a tiny fixture written
in the corpus layout (bran-corpus-manifest/1 + passages.jsonl), so nothing here
needs the real corpus-cache/. One optional test reads the real SciFact
passages when the corpus has been built.
"""

import json
import os
import shutil
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
EVIDENCE = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(EVIDENCE))
sys.path.insert(0, EVIDENCE)
sys.path.insert(0, os.path.join(EVIDENCE, "support"))
sys.path.insert(0, HERE)
import canonical  # noqa: E402
import capture  # noqa: E402
import corpus_capture as cc  # noqa: E402
from fixture_server import NoNetwork, tempdir  # noqa: E402

GOLDEN = os.path.join(HERE, "golden", "corpus_captures.json")
LONG = ("Pluto is a dwarf planet in the Kuiper belt, a ring of bodies beyond the orbit of Neptune. "
        "It was the first and the largest Kuiper belt object to be discovered. After Pluto was "
        "discovered in 1930, it was declared the ninth planet from the Sun.")
SHORT = "Neptune is the eighth planet."
PASSAGES = [
    {"key": "fever17:Pluto:0", "page_id": "Pluto", "chunk": 0, "title": "Pluto", "sent_ids": [0, 2], "text": LONG},
    {"key": "fever17:Neptune:0", "page_id": "Neptune", "chunk": 0, "title": "Neptune", "sent_ids": [0, 0], "text": SHORT},
    {"key": "fever17:AC/DC:1", "page_id": "AC/DC", "chunk": 1, "title": "AC/DC", "sent_ids": [3, 4],
     "text": "AC/DC are an Australian rock band formed in Sydney in 1973 by Scottish-born brothers Malcolm and Angus "
             "Young. Their music has been variously described as hard rock, blues rock, and heavy metal; the band "
             "calls it simply “rock and roll”."},
    {"key": "fever17:Blank:0", "page_id": "Blank", "chunk": 0, "title": " ", "sent_ids": [0, 0], "text": "\t "},
]
CORPUS_SHA = "c0" * 32


def write_corpus(root, corpus_sha=CORPUS_SHA, passages=PASSAGES):
    """A corpus in the corpus layout: tools/corpus/corpus_manifest.json + corpus-cache/fever17/passages.jsonl."""
    os.makedirs(os.path.join(root, "tools", "corpus"))
    os.makedirs(os.path.join(root, "corpus-cache", "fever17"))
    pfile = os.path.join(root, "corpus-cache", "fever17", "passages.jsonl")
    data = "".join(canonical.canonical_json(p) + "\n" for p in passages).encode("utf-8")
    with open(pfile, "wb") as fh:
        fh.write(data)
    m = {"format": "bran-corpus-manifest/1", "versions": {},
         "corpora": {"fever17": {"corpus_sha256": corpus_sha, "license": "CC BY-SA 3.0",
                                 "key_format": "fever17:<page_id>:<chunk>",
                                 "passages": {"file": "corpus-cache/fever17/passages.jsonl",
                                              "n_passages": len(passages),
                                              "passages_sha256": canonical.sha256_hex(data)}}}}
    mpath = os.path.join(root, "tools", "corpus", "corpus_manifest.json")
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(m, fh)
    return mpath


class Base(unittest.TestCase):
    def setUp(self):
        self.guard = NoNetwork().__enter__()
        self.addCleanup(self.guard.__exit__)
        self.root = tempdir()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.manifest = write_corpus(self.root)
        self.src = cc.CorpusSource.from_manifest(self.manifest, "fever17")
        self.cache = capture.Cache(os.path.join(self.root, "cache"))

    def tearDown(self):
        self.assertEqual(self.guard.attempts, [], "corpus capture must not open any connection")

    def cap(self, keys, **kw):
        return cc.capture_passages(keys, self.src, self.cache, **kw)


class IdentifierTests(unittest.TestCase):
    def test_url_round_trip_and_canonical_only(self):
        for key in ["fever17:Pluto:0", "fever17:AC/DC_(band)#é?x=1 %:2", "scifact:4983:0", "P7", "k" * 1024]:
            url = cc.corpus_url("fever17", key)
            self.assertEqual(cc.parse_corpus_url(url), ("fever17", key), key)
            self.assertNotIn("/", url[len("corpus://fever17/"):])
        self.assertEqual(cc.corpus_url("fever17", "fever17:AC/DC:1"), "corpus://fever17/fever17:AC%2FDC:1")
        for bad in ["https://fever17/k", "corpus://Fever17/k", "corpus://fever17/", "corpus://fever17", "corpus:///k",
                    "corpus://fever17/a/b", "corpus://fever17/a b", "corpus://fever17/%c3%a9", "corpus://fever17/%41",
                    "corpus://fever17/%3", "corpus://fever17/%FF", "corpus://fever17/é",
                    "corpus://c/" + "k" * 1025]:
            self.assertIsNone(cc.parse_corpus_url(bad), bad)
        for cid, key in [("Fever", "k"), ("", "k"), ("fever17", ""), ("fever17", "k" * 1025), ("fever17", None)]:
            with self.assertRaises(cc.CorpusError):
                cc.corpus_url(cid, key)

    def test_citation_labels_map_through_retrieval_record(self):
        ret = {"schema": "bran-retrieval/1", "corpus_id": "fever17", "k": 2,
               "results": [{"passage_key": "fever17:Pluto:0", "score_q": 9000},
                           {"passage_key": "fever17:Neptune:0", "score_q": 8000}]}
        self.assertEqual(cc.citation_keys(ret, ["P2", "P1", "P3", "P0", "p1", "X"]),
                         ["fever17:Neptune:0", "fever17:Pluto:0", "P3", "P0", "p1", "X"])
        with self.assertRaises(cc.CorpusError):
            cc.citation_keys(ret, ["P1"], corpus_id="scifact")


class RecordTests(Base):
    def test_record_fields_match_design_table(self):
        [(k, cid, rec)] = self.cap(["fever17:Pluto:0"])
        url = "corpus://fever17/fever17:Pluto:0"
        content = cc.passage_content("Pluto", LONG)
        self.assertEqual(rec["format"], "bran-capture/1")
        self.assertEqual(rec["identifier_kind"], "corpus")
        for f in ("requested", "request_url", "resolved_url", "canonical_url"):
            self.assertEqual(rec[f], url, f)
        self.assertEqual(rec["redirects"], [])
        self.assertIsNone(rec["http_status"])
        self.assertEqual(rec["content_type"], "text/plain")
        self.assertEqual(rec["content_sha256"], canonical.sha256_hex(content.encode("utf-8")))
        self.assertEqual(rec["content_length"], len(content.encode("utf-8")))
        self.assertFalse(rec["truncated"])
        self.assertEqual(rec["extraction"]["method"], "corpus/1")
        self.assertEqual(rec["extraction"]["text_chars"], len(content))
        self.assertEqual(rec["robots"], {"checked": False, "allowed": None, "robots_sha256": None})
        self.assertEqual(rec["license_note"], "CC BY-SA 3.0")
        self.assertEqual(rec["outcome"], "ok")
        self.assertIn(".c" + CORPUS_SHA + ".", rec["capture_tool_version"])
        self.assertEqual(cid, canonical.record_id(rec))
        self.assertEqual(cc.xref_key(url), "corpus:fever17/fever17:Pluto:0")

    def test_outcomes(self):
        res = {k: rec for k, _, rec in self.cap(["fever17:Pluto:0", "fever17:Neptune:0", "fever17:Blank:0",
                                                  "fever17:Missing:0", "P7"])}
        self.assertEqual(res["fever17:Pluto:0"]["outcome"], "ok")
        # No 200-char web threshold: a short passage is ok (ok_rule corpus-nonempty/1).
        self.assertLess(res["fever17:Neptune:0"]["extraction"]["text_chars"], 200)
        self.assertEqual(res["fever17:Neptune:0"]["outcome"], "ok")
        # Empty after normalization: ok_no_text, still hashed and extracted.
        self.assertEqual(res["fever17:Blank:0"]["outcome"], "ok_no_text")
        self.assertEqual(res["fever17:Blank:0"]["extraction"]["text_chars"], 0)
        for k in ("fever17:Missing:0", "P7"):
            r = res[k]
            self.assertEqual(r["outcome"], "invalid_identifier")
            for f in ("resolved_url", "canonical_url", "content_type", "content_sha256", "extraction", "license_note"):
                self.assertIsNone(r[f], f)
            self.assertEqual(r["content_length"], 0)

    def test_deterministic_and_one_record_per_passage(self):
        a = self.cap(["fever17:Pluto:0", "fever17:Pluto:0"])
        self.assertEqual(len(a), 1)
        other = capture.Cache(os.path.join(self.root, "cache2"))
        b = cc.capture_passages(["fever17:Pluto:0"], self.src, other)
        self.assertEqual(a[0][1], b[0][1])
        with open(self.cache.record_path(a[0][1]), "rb") as f1, open(other.record_path(b[0][1]), "rb") as f2:
            self.assertEqual(f1.read(), f2.read())
        # second run reuses the indexed record (no corpus read needed)
        self.src.passages_path = os.path.join(self.root, "nonexistent.jsonl")
        self.assertEqual(self.cap(["fever17:Pluto:0"])[0][1], a[0][1])

    def test_ok_rule_is_pinned(self):
        self.assertEqual(cc.make_config()["ok_rule"], "corpus-nonempty/1")
        with self.assertRaises(cc.CorpusError):
            cc.make_config(ok_rule="min200/1")
        v = cc.tool_version(cc.make_config(), CORPUS_SHA)
        cc.OK_RULES["test-min200/1"] = lambda t: len(t) >= 200
        self.addCleanup(cc.OK_RULES.pop, "test-min200/1")
        cfg = cc.make_config(ok_rule="test-min200/1")
        self.assertNotEqual(cc.tool_version(cfg, CORPUS_SHA), v)
        rec, _, _ = cc.build_record("fever17", "fever17:Neptune:0", cc.passage_content("Neptune", SHORT), None, "v", cfg)
        self.assertEqual(rec["outcome"], "ok_no_text")

    def test_new_corpus_means_new_capture_ids(self):
        root2 = tempdir()
        self.addCleanup(shutil.rmtree, root2, True)
        src2 = cc.CorpusSource.from_manifest(write_corpus(root2, corpus_sha="d1" * 32), "fever17")
        a = self.cap(["fever17:Pluto:0"])[0]
        b = cc.capture_passages(["fever17:Pluto:0"], src2, capture.Cache(os.path.join(root2, "cache")))[0]
        self.assertEqual(a[2]["content_sha256"], b[2]["content_sha256"])
        self.assertNotEqual(a[1], b[1])

    def test_no_floats_and_rust_compatible_canonical_bytes(self):
        for _, cid, rec in self.cap(["fever17:Pluto:0", "fever17:AC/DC:1", "nope"]):
            self.assertEqual(canonical.canonical_json(rec), canonical.canonical_json(json.loads(canonical.canonical_json(rec))))
            self.assertEqual(cid, canonical.record_id(rec))

    def test_golden_fixture(self):
        with open(GOLDEN, encoding="utf-8") as fh:
            g = json.load(fh)
        self.assertEqual(len(g["cases"]), 4)
        for case in g["cases"]:
            rec, _, _ = cc.build_record(case["corpus_id"], case["passage_key"], case["content"],
                                        case["license_note"], case["capture_tool_version"])
            self.assertEqual(rec, case["record"], case["name"])
            self.assertEqual(canonical.canonical_json(rec), case["canonical_json"], case["name"])
            self.assertEqual(canonical.record_id(rec), case["capture_id"], case["name"])
            if rec["canonical_url"]:
                self.assertEqual(cc.xref_key(rec["canonical_url"]), case["xref_key"])


class CacheTests(Base):
    def test_offline_replay_and_miss(self):
        online = self.cap(["fever17:Pluto:0", "fever17:Neptune:0", "P7"])
        off = self.cap(["fever17:Pluto:0", "fever17:Neptune:0", "P7"], offline=True)
        self.assertEqual([x[1:] for x in online], [x[1:] for x in off])
        before = sorted(os.listdir(os.path.join(self.cache.root, "captures")))
        with open(os.path.join(self.cache.root, "index", "captures.jsonl"), "rb") as fh:
            idx = fh.read()
        with self.assertRaises(capture.CacheMiss):
            self.cap(["fever17:Pluto:0", "fever17:AC/DC:1"], offline=True)
        self.assertEqual(sorted(os.listdir(os.path.join(self.cache.root, "captures"))), before)
        with open(os.path.join(self.cache.root, "index", "captures.jsonl"), "rb") as fh:
            self.assertEqual(fh.read(), idx)
        # another epoch is another record set
        with self.assertRaises(capture.CacheMiss):
            self.cap(["fever17:Pluto:0"], offline=True, epoch="other")

    def test_verify_cache_and_tamper(self):
        [(_, cid, rec)] = self.cap(["fever17:Pluto:0"])
        self.assertEqual(self.cache.verify(), [])
        tp = self.cache.text_path(rec["extraction"]["text_sha256"])
        with open(tp, "rb") as fh:
            data = fh.read()
        with open(tp, "wb") as fh:
            fh.write(data[:-1] + b"X")
        self.assertTrue(any("text hash mismatch" in p for p in self.cache.verify()))
        with open(tp, "wb") as fh:
            fh.write(data)
        rp = self.cache.record_path(cid)
        with open(rp, "rb") as fh:
            raw = fh.read()
        with open(rp, "wb") as fh:
            fh.write(raw.replace(b'"ok"', b'"ok_no_text"'))
        self.assertTrue(any(cid in p for p in self.cache.verify()))

    def test_telemetry_is_not_sealed(self):
        [(_, cid, _)] = self.cap(["fever17:Pluto:0"])
        tp = os.path.join(self.cache.root, "captures", cid + ".telemetry.json")
        with open(tp, "w", encoding="utf-8") as fh:
            json.dump([{"edited": True}], fh)
        self.assertEqual(self.cache.verify(), [])
        self.assertEqual(self.cap(["fever17:Pluto:0"], offline=True)[0][1], cid)

    def test_support_checker_reads_corpus_captures(self):
        import check  # tools/evidence/support/check.py
        [(_, cid, rec)] = self.cap(["fever17:Pluto:0"])
        loaded = check.load_capture(self.cache.root, cid)
        self.assertEqual(loaded, rec)
        self.assertEqual(check.load_capture_text(self.cache.root, loaded), cc.passage_content("Pluto", LONG))


class AdapterTests(Base):
    def test_manifest_adapter(self):
        self.assertEqual(self.src.corpus_sha256, CORPUS_SHA)
        self.assertEqual(self.src.license_note, "CC BY-SA 3.0")
        self.src.verify_passages()
        with open(self.src.passages_path, "ab") as fh:
            fh.write(b"\n")
        with self.assertRaises(cc.CorpusError):
            self.src.verify_passages()
        with self.assertRaises(cc.CorpusError):
            cc.CorpusSource.from_manifest(self.manifest, "scifact")
        self.assertEqual(self.src.lookup(["fever17:AC/DC:1", "zzz"]),
                         {"fever17:AC/DC:1": cc.passage_content("AC/DC", PASSAGES[2]["text"])})

    def test_cli(self):
        out = os.path.join(self.root, "out.jsonl")
        keys = os.path.join(self.root, "keys.txt")
        with open(keys, "w", encoding="utf-8") as fh:
            fh.write("fever17:Pluto:0\n{\"key\": \"fever17:Blank:0\"}\n")
        base = ["--manifest", self.manifest, "--corpus", "fever17", "--cache", self.cache.root]
        self.assertEqual(cc.main(["capture", *base, "--keys", keys, "--key", "P9", "--out", out, "--verify-passages"]), 0)
        with open(out, encoding="utf-8") as fh:
            lines = [json.loads(x) for x in fh]
        self.assertEqual([x["outcome"] for x in lines], ["invalid_identifier", "ok", "ok_no_text"])  # --key first, then --keys
        self.assertEqual(cc.main(["capture", *base, "--key", "fever17:Pluto:0", "--offline", "--out", out]), 0)
        self.assertEqual(cc.main(["capture", *base, "--key", "fever17:AC/DC:1", "--offline", "--out", out]), 3)


@unittest.skipUnless(os.path.exists(os.path.join(REPO, "corpus-cache", "scifact", "passages.jsonl")),
                     "SciFact corpus passages not built")
class RealSciFactTests(unittest.TestCase):
    def test_capture_first_scifact_passage(self):
        src = cc.CorpusSource.from_manifest(os.path.join(REPO, "tools", "corpus", "corpus_manifest.json"), "scifact")
        with open(src.passages_path, encoding="utf-8") as fh:
            first = json.loads(fh.readline())
        tmp = tempdir()
        self.addCleanup(shutil.rmtree, tmp, True)
        with NoNetwork():
            [(_, cid, rec)] = cc.capture_passages([first["key"]], src, capture.Cache(tmp))
        self.assertEqual(rec["content_sha256"],
                         canonical.sha256_hex(cc.passage_content(first["title"], first["text"]).encode("utf-8")))
        self.assertEqual(rec["request_url"], cc.corpus_url("scifact", first["key"]))
        self.assertEqual(rec["license_note"], src.license_note)


if __name__ == "__main__":
    unittest.main()
