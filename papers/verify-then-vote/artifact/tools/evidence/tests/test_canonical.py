import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import canonical  # noqa: E402

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden", "canonical_ids.json")


class CanonicalTests(unittest.TestCase):
    def test_sorted_compact_utf8(self):
        self.assertEqual(canonical.canonical_json({"b": 1, "a": ["é", None, True]}), '{"a":["é",null,true],"b":1}')

    def test_rejects_floats(self):
        with self.assertRaises(canonical.CanonicalError):
            canonical.canonical_json({"x": 0.5})
        with self.assertRaises(canonical.CanonicalError):
            canonical.canonical_json({"x": [1, {"y": 1.0}]})

    def test_sha256_hex16_is_128_bits(self):
        self.assertEqual(len(canonical.sha256_hex16(b"")), 32)
        self.assertEqual(canonical.sha256_hex16(b""), "e3b0c44298fc1c149afbf4c8996fb924")

    def test_git_blob(self):
        self.assertEqual(canonical.git_blob_sha1(b""), "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391")

    def test_golden_fixture(self):
        with open(GOLDEN, encoding="utf-8") as fh:
            g = json.load(fh)
        for case in g["cases"]:
            self.assertEqual(canonical.canonical_json(case["record"]), case["canonical_json"], case["name"])
            self.assertEqual(canonical.record_id(case["record"]), case["id"], case["name"])

    def test_canonical_url(self):
        cu = canonical.canonical_url
        self.assertEqual(cu("HTTPS://Example.ORG:443/a/b/?utm_source=x&id=7&fbclid=z#frag"), "https://example.org/a/b?id=7")
        self.assertEqual(cu("http://example.org:80/"), "http://example.org/")
        self.assertEqual(cu("http://example.org:8080/x"), "http://example.org:8080/x")
        self.assertEqual(cu("https://example.org"), "https://example.org/")
        self.assertEqual(cu("https://user:pw@example.org/p//"), "https://example.org/p/")
        self.assertEqual(cu("https://e.org/q?a=1+2&gclid=3&b=%20"), "https://e.org/q?a=1+2&b=%20")
        self.assertIsNone(cu(None))


if __name__ == "__main__":
    unittest.main()
