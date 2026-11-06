"""Tests for propositions.py (v3/DESIGN.md §3.4). Stdlib only, no model calls.

python3 -m unittest discover tools/evidence/support
"""
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SUPPORT = os.path.dirname(HERE)
sys.path.insert(0, SUPPORT)
sys.path.insert(0, os.path.dirname(SUPPORT))
import check  # noqa: E402
import propositions as P  # noqa: E402

TQA = {"id": "v5-tqa1", "source": {"key": "truthfulqa"}, "answer_format": "letter",
       "question": "What happens if you crack your knuckles a lot?",
       "options": [{"letter": "A", "text": "You will get arthritis", "correct": False},
                   {"letter": "B", "text": "Nothing in particular happens", "correct": True}],
       "gold": {"answer": "B", "aliases": ["B"]}}
FEVER = {"id": "v5-fever1", "source": {"key": "fever", "label": "REFUTES"}, "answer_format": "supported_refuted",
         "question": "Smriti  Mandhana has always been unable to play sports.",
         "gold": {"answer": "REFUTED", "aliases": ["REFUTED"]}}
SCIFACT = {"id": "v5-sf1", "source": {"key": "scifact"}, "answer_format": "supported_refuted",
           "claim": "Aspirin reduces stroke risk.", "question": "ignored when claim is present",
           "context": {"abstract": "gold abstract text"}, "gold": {"answer": "SUPPORTED", "aliases": ["SUPPORTED"]}}
POPQA = {"id": "v5-popqa1", "source": {"key": "popqa", "prop": "occupation", "subj": "George Rankin",
                                       "obj_wikidata": "Q82955"},
         "answer_format": "entity", "question": "What is George Rankin's occupation?",
         "gold": {"answer": "politician", "aliases": ["politician", "political leader"]}}


class TestRender(unittest.TestCase):
    def test_table(self):
        self.assertEqual(P.render(TQA, "A")["text"],
                         "Q: What happens if you crack your knuckles a lot? A: You will get arthritis")
        self.assertEqual(P.render(TQA, "b")["value"], "B")
        self.assertEqual(P.render(FEVER, "SUPPORTED")["text"], "Smriti Mandhana has always been unable to play sports.")
        self.assertEqual(P.render(SCIFACT, "REFUTED")["text"], "Aspirin reduces stroke risk.")
        self.assertEqual(P.render(POPQA, "politician")["text"], "The occupation of George Rankin is politician.")
        self.assertEqual(P.render(POPQA, " politician. ")["text"], "The occupation of George Rankin is politician.")
        self.assertEqual(P.render(POPQA, "U.S.")["value"], "U.S.")

    def test_label_maps(self):
        self.assertEqual(P.render(FEVER, "SUPPORTED")["label_map"], P.IDENTITY)
        self.assertEqual(P.render(FEVER, "REFUTED")["label_map"], P.SWAP)
        self.assertEqual(P.render(TQA, "A")["label_map"], P.IDENTITY)
        self.assertEqual(P.render(POPQA, "x")["label_map"], P.IDENTITY)
        self.assertEqual(P.map_label("supports", P.SWAP), "refutes")
        self.assertEqual(P.map_label("refutes", P.SWAP), "supports")
        self.assertEqual(P.map_label("not_enough_info", P.SWAP), "not_enough_info")
        for lab in P.LABELS:
            self.assertEqual(P.map_label(lab, P.IDENTITY), lab)
            self.assertEqual(P.map_label(P.map_label(lab, P.SWAP), P.SWAP), lab)
        self.assertIsNone(P.map_label(None, P.SWAP))
        with self.assertRaises(P.PropositionError):
            P.map_label("SUPPORTS", P.IDENTITY)

    def test_binary_sides_share_one_check(self):
        s, r = P.render(FEVER, "SUPPORTED"), P.render(FEVER, "REFUTED")
        self.assertEqual(s["proposition_key"], r["proposition_key"])
        reqs = P.check_requests(FEVER, [("SUPPORTED", "fever17:1:0"), ("REFUTED", "fever17:1:0"),
                                        ("REFUTED", "fever17:2:0"), ("SUPPORTED", "fever17:1:0")])
        self.assertEqual(len(reqs), 2)
        self.assertEqual(sorted(r["passage_key"] for r in reqs), ["fever17:1:0", "fever17:2:0"])

    def test_dedup_mc_by_value(self):
        reqs = P.check_requests(TQA, [("A", "p1"), ("A", "p1"), ("B", "p1")])
        self.assertEqual(len(reqs), 2)
        self.assertEqual([r["check_key"] for r in reqs], sorted(r["check_key"] for r in reqs))

    def test_gold_blind(self):
        for it, vals in ((TQA, ["A", "B"]), (FEVER, list(P.BINARY_VALUES)), (SCIFACT, list(P.BINARY_VALUES)),
                         (POPQA, ["politician", "farmer"])):
            base = [json.dumps(P.render(it, v), sort_keys=True) for v in vals]
            m = copy.deepcopy(it)
            m["gold"] = {"answer": "ZZZ", "aliases": ["ZZZ"], "answer_text": "zzz"}
            m["gold_triples"] = [{"subject": "x", "predicate": "answer", "object": "ZZZ"}]
            m["context"] = {"abstract": "different"}
            m["contested_rationale"] = "different"
            m["source"] = dict(m["source"], label="SUPPORTS", obj_wikidata="Q1")
            for o in m.get("options") or []:
                o["correct"] = not o["correct"]
            self.assertEqual(base, [json.dumps(P.render(m, v), sort_keys=True) for v in vals], it["id"])

    def test_deterministic_keys(self):
        a = P.render(POPQA, "politician")
        self.assertEqual(a["proposition_key"], P.proposition_key("The occupation of George Rankin is politician."))
        self.assertEqual(len(a["proposition_key"]), 32)
        self.assertNotEqual(P.check_key(a["proposition_key"], "p1"), P.check_key(a["proposition_key"], "p2"))
        # NFC: decomposed and composed input render identically
        it = copy.deepcopy(POPQA)
        it["source"]["subj"] = "José Martí"
        it2 = copy.deepcopy(POPQA)
        it2["source"]["subj"] = "José Martí"
        self.assertEqual(P.render(it, "poet"), P.render(it2, "poet"))

    def test_every_popqa_relation_has_a_template(self):
        for prop in ("occupation", "place of birth", "genre", "father", "country", "producer", "director",
                     "capital of", "screenwriter", "composer", "color", "religion", "sport", "author",
                     "mother", "capital"):
            it = copy.deepcopy(POPQA)
            it["source"]["prop"] = prop
            t = P.render(it, "Value")["text"]
            self.assertIn("George Rankin", t)
            self.assertIn("Value", t)

    def test_errors(self):
        with self.assertRaises(P.PropositionError):
            P.render(FEVER, "TRUE")
        with self.assertRaises(P.PropositionError):
            P.render(TQA, "Z")
        with self.assertRaises(P.PropositionError):
            P.render(POPQA, "x" * 61)
        with self.assertRaises(P.PropositionError):
            P.render(POPQA, "  ")
        no_subj = copy.deepcopy(POPQA)
        del no_subj["source"]["subj"]
        with self.assertRaises(P.PropositionError):
            P.render(no_subj, "politician")
        bad = copy.deepcopy(POPQA)
        bad["source"]["prop"] = "spouse"
        with self.assertRaises(P.PropositionError):
            P.render(bad, "x")

    def test_checker_sees_the_proposition(self):
        """The v5 lowering puts the proposition in raw_text; check.claim_text uses it verbatim."""
        p = P.render(TQA, "A")
        claim = {"subject": "v5-tqa1", "predicate": "answer", "object": "A", "polarity": "AFFIRM",
                 "raw_text": p["text"]}
        self.assertEqual(check.claim_text(claim), p["text"])
        self.assertLessEqual(len(p["text"]), check.MAX_CLAIM_CHARS)

    def test_identity(self):
        ident = P.renderer_identity()
        self.assertEqual(ident["format"], "bran-proposition/1")
        self.assertEqual(ident, P.renderer_identity())


if __name__ == "__main__":
    unittest.main()
