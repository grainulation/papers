import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import extract  # noqa: E402

REPO = os.path.dirname(os.path.dirname(ROOT))
RAW = os.path.join(REPO, "real-agent-eval", "v3", "results", "raw")
RESULTS = os.path.join(REPO, "real-agent-eval", "v3", "results")


def ids(text):
    return [(d["kind"], d["requested"]) for d in extract.find_identifiers(text)]


class FindIdentifiers(unittest.TestCase):
    def test_url_trailing_punctuation(self):
        self.assertEqual(ids("See https://example.org/a/b."), [("url", "https://example.org/a/b")])
        self.assertEqual(ids("(https://example.org/x), next"), [("url", "https://example.org/x")])
        self.assertEqual(ids('"https://example.org/q?a=1";'), [("url", "https://example.org/q?a=1")])

    def test_balanced_parens_kept(self):
        self.assertEqual(ids("see https://en.wikipedia.org/wiki/Pluto_(dwarf_planet)."),
                         [("url", "https://en.wikipedia.org/wiki/Pluto_(dwarf_planet)")])

    def test_markdown_link(self):
        self.assertEqual(ids("[BIPM](https://www.bipm.org/en/si/) and **https://a.org/b**"),
                         [("url", "https://www.bipm.org/en/si/"), ("url", "https://a.org/b")])

    def test_bare_www(self):
        self.assertEqual(ids("visit www.nasa.gov/pluto today"), [("url", "https://www.nasa.gov/pluto")])

    def test_doi_forms_share_identity(self):
        a = ids("doi:10.1161/JAHA.119.013097.")
        b = ids("https://doi.org/10.1161/jaha.119.013097")
        c = ids("10.1161/JAHA.119.013097")
        self.assertEqual(a, [("doi", "10.1161/jaha.119.013097")])
        self.assertEqual(a, b)
        self.assertEqual(a, c)
        d = extract.find_identifiers("doi:10.1161/JAHA.119.013097")[0]
        self.assertEqual(d["request_url"], "https://doi.org/10.1161/jaha.119.013097")

    def test_doi_inside_url_not_double_counted(self):
        self.assertEqual(len(ids("https://doi.org/10.1080/00261394.2018.1502801 (NIST)")), 1)

    def test_arxiv_rfc_pmid_isbn(self):
        self.assertEqual(ids("arXiv:1602.01074v2"), [("arxiv", "1602.01074v2")])
        self.assertEqual(ids("https://arxiv.org/abs/astro-ph/0610401"), [("arxiv", "astro-ph/0610401")])
        self.assertEqual(ids("see RFC 793 and RFC-1122"), [("rfc", "RFC793"), ("rfc", "RFC1122")])
        self.assertEqual(ids("PMID: 12345678"), [("pmid", "12345678")])
        self.assertEqual(ids("https://pubmed.ncbi.nlm.nih.gov/12345678/"), [("pmid", "12345678")])
        self.assertEqual(ids("ISBN 978-0-13-468599-1"), [("isbn", "9780134685991")])
        r = extract.find_identifiers("RFC 793")[0]
        self.assertEqual(r["request_url"], "https://www.rfc-editor.org/rfc/rfc793.txt")
        self.assertIsNone(extract.find_identifiers("ISBN 0-306-40615-2")[0]["request_url"])

    def test_rejects_garbage(self):
        self.assertEqual(ids("https://' and http://localhost"), [])
        self.assertEqual(ids("x" * 10 + "https://a.org/" + "b" * 3000), [])

    def test_offsets(self):
        t = "Canberra (https://www.australia.gov.au/x)."
        d = extract.find_identifiers(t)[0]
        self.assertEqual(t[d["start"]:d["end"]], "https://www.australia.gov.au/x")


class Association(unittest.TestCase):
    RESP = ("The capital of Australia is Canberra.\n\nConfidence level: High\n\n"
            "Sources:\n- Australian Government (2021). https://www.australia.gov.au/canberra\n"
            "- doi:10.1000/xyz123\n\n"
            "Pluto was reclassified in 2006 (https://www.iau.org/news/pr0603/).")

    def test_supports_sentence(self):
        a = extract.analyze_response(self.RESP)
        by = {d["requested"]: d for d in a["identifiers"]}
        self.assertEqual(by["https://www.australia.gov.au/canberra"]["supports"], "The capital of Australia is Canberra.")
        self.assertEqual(by["10.1000/xyz123"]["supports"], "The capital of Australia is Canberra.")
        self.assertTrue(by["10.1000/xyz123"]["in_source_line"])
        iau = by["https://www.iau.org/news/pr0603/"]
        self.assertFalse(iau["in_source_line"])
        self.assertTrue(iau["supports"].startswith("Pluto was reclassified"))

    def test_claim_window_extended(self):
        got = extract.identifiers_for_claim(self.RESP, "The capital of Australia is Canberra.")
        self.assertEqual([d["requested"] for d in got], ["https://www.australia.gov.au/canberra", "10.1000/xyz123"])
        got = extract.identifiers_for_claim(self.RESP, "Pluto was reclassified in 2006 (https://www.iau.org/news/pr0603/).")
        self.assertEqual([d["kind"] for d in got], ["url"])

    def test_claim_window_v1_port(self):
        r = "TCP is reliable. Source: RFC 793. It uses ACKs."
        self.assertEqual([d["requested"] for d in extract.identifiers_for_claim(r, "TCP is reliable.", "v1")], ["RFC793"])


@unittest.skipUnless(os.path.isdir(RAW), "v3 raw results not present")
class CorpusRecovery(unittest.TestCase):
    """Acceptance 5: >= 95% of reference-regex URLs/DOIs recovered."""

    def test_reference_recall(self):
        m = extract.measure(RAW)
        tot = m["reference_regex"]["total"]
        self.assertGreaterEqual(tot["found"], 400)
        self.assertGreaterEqual(tot["recovered"] / tot["found"], 0.95)
        self.assertEqual(m["responses"], 275)

    def test_per_claim_runs(self):
        pc = extract.measure_claims(RESULTS)
        self.assertGreater(pc["claims"], 0)
        self.assertGreaterEqual(pc["extended"]["claims_with_any"], pc["v1"]["claims_with_any"])


if __name__ == "__main__":
    unittest.main()
