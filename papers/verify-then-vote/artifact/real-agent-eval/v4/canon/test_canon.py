#!/usr/bin/env python3
"""Unit tests for canon.py.  Run:  python3 -m unittest test_canon  (from this directory)."""

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from canon import (CANON_VERSION, SYNONYMS, SYNONYM_SOURCES, canon,  # noqa: E402
                   negation_count, rust_normalize_object)

EVAL = HERE.parent.parent


def same(a, b):
    return canon(a) == canon(b)


class Merges(unittest.TestCase):
    """Formatting-only variants observed in v1orig / v3 must merge."""

    def test_markdown(self):
        self.assertTrue(same("**Canberra**", "Canberra"))           # q01 (both datasets)
        self.assertTrue(same("the **Pacific Ocean**", "the Pacific Ocean"))   # q06
        self.assertTrue(same("**more than five senses**", "more than five senses"))  # v3 q48
        self.assertTrue(same("`x`", "x"))

    def test_whitespace_case_punct(self):
        self.assertTrue(same("  Pacific   OCEAN. ", "pacific ocean"))
        self.assertTrue(same("evolution?", "evolution"))           # v3 q25 'what is'

    def test_articles(self):
        self.assertTrue(same("a myth", "myth"))
        self.assertTrue(same("the Pacific Ocean", "Pacific Ocean"))

    def test_numbers(self):
        self.assertTrue(same("299,792,458 m/s", "299792458 m/s"))
        self.assertTrue(same("3.00 x 10^8", "3 x 10^8"))
        self.assertTrue(same("three-way handshake", "a 3-way handshake"))
        self.assertTrue(same("twenty-three pairs", "23 pairs"))
        self.assertTrue(same("more than five senses", "more than 5 senses"))

    def test_units(self):
        self.assertTrue(same("approximately 299,792,458 meters per second (m/s)",
                             "**299,792,458 meters per second**"))      # v3 q02
        self.assertTrue(same("approximately 299,792 kilometers per second (299,792 km/s)",
                             "299,792 km/s"))
        self.assertTrue(same("100 degrees Celsius", "100 °C"))
        self.assertTrue(same("100 degrees Celsius (°C)", "100°C"))
        self.assertTrue(same("27 percent", "27%"))
        self.assertTrue(same("93 million miles", "93 million mi"))

    def test_hedge(self):
        self.assertTrue(same("approximately 93 million miles", "93 million miles"))
        self.assertTrue(same("about 30 feet", "30 ft"))
        self.assertTrue(same("~5%", "5 percent"))

    def test_plural(self):
        self.assertTrue(same("46 chromosomes", "46 chromosome"))
        self.assertTrue(same("strengths and weaknesses", "strength and weakness"))
        self.assertTrue(same("12 hours", "12 hour"))

    def test_a_unit_is_one(self):
        self.assertTrue(same("a memory span of up to a month",
                             "a memory span of up to one month"))   # v1orig q23

    def test_acronym_paren(self):
        self.assertTrue(same("known as an Astronomical Unit (AU)", "known as an astronomical unit"))
        self.assertTrue(same("also known as an Astronomical Unit (AU)",
                             "known as an Astronomical Unit (AU)"))  # v1orig q13 ('this distance','is')

    def test_citations(self):
        self.assertTrue(same("about 5% (2)", "about 5%"))
        self.assertTrue(same("a consensus (Hoffman, 2018)", "a consensus"))
        self.assertTrue(same("difficult to distinguish (source: NASA)", "difficult to distinguish"))
        self.assertTrue(same("30 feet wide (National Geographic, n.d.)", "30 feet wide"))

    def test_synonyms(self):
        self.assertTrue(same("a misconception", "a myth"))          # v3 q23
        self.assertTrue(same("ineffective against viruses", "not effective against viruses"))  # q46

    def test_contractions(self):
        self.assertTrue(same("doesn't interact", "does not interact"))
        self.assertTrue(same("it's not", "it is not"))
        self.assertTrue(same("Earth's curvature", "Earth curvature"))


class NonMerges(unittest.TestCase):
    """Adversarial: objects that differ in meaning must NOT merge."""

    def test_negation(self):
        for a, b in [("not a liquid", "a liquid"), ("a planet", "not a planet"),
                     ("effective against viruses", "ineffective against viruses"),
                     ("effective", "not effective"), ("is visible", "isn't visible"),
                     ("can be liquefied", "cannot be liquefied"), ("no evidence", "evidence"),
                     ("never strikes twice", "strikes twice"), ("with side effects", "without side effects"),
                     ("not unusually short", "unusually short")]:
            self.assertFalse(same(a, b), (a, b))

    def test_numbers_differ(self):
        for a, b in [("3 seconds", "30 seconds"), ("9 seconds, not 3 seconds", "3 seconds"),
                     ("27%", "85%"), ("149.6 million km", "150 million km"),
                     ("93 million miles", "93 million km"), ("46 chromosomes", "23 chromosomes"),
                     ("up to one month", "up to three months"), ("5 feet 7 inches", "5 feet 6 inches"),
                     ("299,792 km/s", "299,792,458 m/s"), ("-183 degrees Celsius", "183 degrees Celsius"),
                     ("100 °C", "100 °F"), ("1.7", "1.07"), ("12 hours", "12 minutes")]:
            self.assertFalse(same(a, b), (a, b))

    def test_quantifier_words_kept(self):
        for a, b in [("up to 3 months", "3 months"), ("more than 5 senses", "5 senses"),
                     ("over 13,000 miles", "13,000 miles"), ("nearly 30%", "30%"),
                     ("at least 5", "5"), ("a common myth", "a myth"),
                     ("a strong scientific consensus", "a scientific consensus")]:
            self.assertFalse(same(a, b), (a, b))

    def test_protocols_and_acronyms(self):
        self.assertFalse(same("HTTPS", "HTTP"))
        self.assertFalse(same("https", "http"))
        self.assertFalse(same("sometimes", "sometime"))
        self.assertFalse(same("CORS", "COR"))

    def test_bare_unit_letters_not_units(self):
        self.assertFalse(same("$5m", "5 meters"))
        self.assertFalse(same("5G", "5 grams"))

    def test_second_is_not_one(self):
        self.assertFalse(same("a second opinion", "1 second opinion"))
        self.assertFalse(same("a second", "1 second"))

    def test_hedge_not_preposition(self):
        self.assertFalse(same("about cats", "cats"))
        self.assertFalse(same("around the sun", "the sun"))

    def test_non_redundant_paren_kept(self):
        self.assertFalse(same("93 million miles (149.6 million kilometers)", "93 million miles"))
        self.assertFalse(same("46 chromosomes (23 pairs)", "46 chromosomes"))
        self.assertFalse(same("vitamin A", "vitamin"))

    def test_distinct_answers(self):
        for a, b in [("Canberra", "Sydney"), ("a myth", "a fact"), ("an amorphous solid", "a liquid"),
                     ("a dwarf planet", "a planet"), ("high", "medium"), ("low", "medium")]:
            self.assertFalse(same(a, b), (a, b))


class Invariants(unittest.TestCase):
    CORPUS = None

    @classmethod
    def setUpClass(cls):
        objs = []
        for d in [EVAL / "results", EVAL / "v3" / "results"]:
            for f in sorted(d.glob("q*.json")):
                with open(f) as fh:
                    resps = json.load(fh)
                for r in resps:
                    objs.extend(c.get("object", "") for c in r.get("claims", []))
        cls.CORPUS = objs + ["", "   ", "**", "-", "The", "a"]

    def test_deterministic_and_idempotent(self):
        for o in self.CORPUS:
            c = canon(o)
            self.assertEqual(c, canon(o))
            self.assertEqual(canon(c), c, o)

    def test_consistent_with_rust_and_python_keys(self):
        for o in self.CORPUS:
            c = canon(o)
            self.assertEqual(rust_normalize_object(c), c, o)   # ir.rs normalize_object
            self.assertEqual(c.lower(), c)                     # compiler.rs value_key
            self.assertEqual(c.lower().strip(), c)             # evaluate_v1 conflict key

    def test_negations_preserved(self):
        for o in self.CORPUS:
            self.assertEqual(negation_count(canon(o)), negation_count(o), o)

    def test_nonempty(self):
        for o in self.CORPUS:
            if o.strip():
                self.assertTrue(canon(o), repr(o))

    def test_synonym_table_documented(self):
        self.assertEqual(set(SYNONYMS), set(SYNONYM_SOURCES))
        for k, v in SYNONYMS.items():
            self.assertEqual(negation_count(" ".join(v)), negation_count(k), k)

    def test_version(self):
        self.assertRegex(CANON_VERSION, r"^canon-\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
