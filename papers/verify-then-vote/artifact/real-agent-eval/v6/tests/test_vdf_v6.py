#!/usr/bin/env python3
"""Unit tests for vdf_v6.py: every branch of rule `vdf-1` on hand-built items, the F1 fixed sequence,
and the design-set hash. No model, no network, no frozen data needed.

Run:  tools/corpus/.venv/bin/python -I real-agent-eval/v6/tests/test_vdf_v6.py
"""
import random
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import vdf_v6 as V  # noqa: E402

E = V.E
ACC: List[str] = [E.PREREG_CHECKER]
SUP: List[Dict[str, Any]] = [{"support_label": "supports", "support_status": "ok", "accepted": True}]
NEI: List[Dict[str, Any]] = [{"support_label": "not_enough_info", "support_status": "ok", "accepted": True}]
UNACC: List[Dict[str, Any]] = [{"support_label": "supports", "support_status": "ok", "accepted": False}]


def resp(value: str, verified: bool = False) -> Dict[str, Any]:
    return {"parsed": value, "audit": SUP if verified else NEI}


def decide(parsed: List[Dict[str, Any]], iid: str = "t-1", d: Optional[str] = None, bg: Optional[str] = None) -> Dict[str, Any]:
    return V.vdf_decide(parsed, iid, d, bg, ACC)


class VddBranches(unittest.TestCase):
    def test_maj_in_w_keeps_maj_even_when_vv_differs(self) -> None:
        # MAJ = a (3 votes, one verified); verified plurality is b (2 verified). VV = b, but MAJ is verified.
        p = [resp("a", True), resp("a"), resp("a"), resp("b", True), resp("b", True)]
        r = decide(p, d="a", bg="b")
        self.assertEqual(r["MAJ"], "a")
        self.assertEqual(r["VV"], "b")
        self.assertEqual(r["VV/VDF"], "a")
        self.assertEqual(r["VV_VDF_branch"], "maj_verified")
        self.assertEqual(r["BE-G/VDF"], "a")            # D = a is verified too
        self.assertEqual(r["BG_VDF_branch"], "d_verified")

    def test_maj_not_in_w_takes_verified_plurality(self) -> None:
        p = [resp("a"), resp("a"), resp("a"), resp("b", True), resp("b", True)]
        r = decide(p, d="a", bg="b")
        self.assertEqual(r["VV/VDF"], "b")
        self.assertEqual(r["VV_VDF_branch"], "vv_over_verified")
        self.assertEqual(r["BE-G/VDF"], "b")            # D = a is unverified, so the gate's winner stands
        self.assertEqual(r["BG_VDF_branch"], "begg_over_verified")
        self.assertEqual(r["W"], ["b"])

    def test_w_empty_returns_maj_and_d(self) -> None:
        p = [resp("a"), resp("a"), resp("b")]
        r = decide(p, d="a", bg="a")
        self.assertEqual(r["VV/VDF"], "a")
        self.assertEqual(r["VV_VDF_branch"], "w_empty")
        self.assertEqual(r["BE-G/VDF"], "a")
        self.assertEqual(r["BG_VDF_branch"], "w_empty")
        self.assertEqual(r["W"], [])

    def test_unaccepted_label_is_not_a_witness(self) -> None:
        p = [{"parsed": "a", "audit": UNACC}, {"parsed": "a", "audit": UNACC}, {"parsed": "b", "audit": NEI}]
        self.assertEqual(decide(p, d="a", bg="a")["W"], [])

    def test_tied_verified_plurality_takes_the_vv_seed(self) -> None:
        # MAJ = a (3, unverified); b and c are each verified once: a tied verified plurality
        for iid in ("t-1", "t-2", "t-3", "t-4", "t-5", "t-6"):
            p = [resp("a"), resp("a"), resp("a"), resp("b", True), resp("c", True)]
            r = decide(p, iid, d="a", bg="b")
            want = random.Random("v5-vv:" + iid).choice(["b", "c"])
            self.assertTrue(r["vv_tied"])
            self.assertEqual(r["VV"], want)
            self.assertEqual(r["VV/VDF"], want)
            self.assertEqual(r["VV_VDF_branch"], "vv_over_verified_tied")
        picks = {decide([resp("a"), resp("a"), resp("a"), resp("b", True), resp("c", True)], f"t-{i}")["VV/VDF"] for i in range(40)}
        self.assertEqual(picks, {"b", "c"})              # the seed really varies the choice (not a fixed tie-break)

    def test_tied_verified_plurality_resolved_by_maj_when_maj_is_one_of_them(self) -> None:
        # a is MAJ and verified once, b verified once: tie among verified, but MAJ in W, so VV/VDF = MAJ without the seed
        p = [resp("a", True), resp("a"), resp("a"), resp("b", True)]
        r = decide(p, d="a", bg="b")
        self.assertEqual(r["VV/VDF"], "a")
        self.assertEqual(r["VV_VDF_branch"], "maj_verified")

    def test_d_differs_from_maj_on_a_tied_majority(self) -> None:
        # a and b tie for the majority; the reducer's D is whichever MAJ did not pick
        iid = next(i for i in (f"tm-{k}" for k in range(50))
                   if random.Random("v5-majority:" + i).choice(["a", "b"]) == "a")      # MAJ = a for this id
        base = [resp("a"), resp("a"), resp("b", True), resp("b", True), resp("c")]
        r = decide(base, iid, d="b", bg="b")
        self.assertEqual(r["MAJ"], "a")
        self.assertTrue(r["majority_tied"])
        self.assertEqual(r["BE-G/VDF"], "b")             # D = b is verified, kept
        self.assertEqual(r["BG_VDF_branch"], "d_verified")
        self.assertEqual(r["VV/VDF"], "b")               # MAJ = a is unverified: VV/VDF follows the verified vote
        # D differs from MAJ and D is unverified, W non-empty: the BE-G winner stands
        p = [resp("a", True), resp("a", True), resp("b"), resp("b"), resp("c")]
        r = decide(p, iid, d="b", bg="a")
        self.assertEqual(r["MAJ"], "a")
        self.assertEqual(r["VV/VDF"], "a")               # MAJ is verified
        self.assertEqual(r["BE-G/VDF"], "a")
        self.assertEqual(r["BG_VDF_branch"], "begg_over_verified")
        # D differs from MAJ and W is empty: VV/VDF = MAJ, BE-G/VDF = D (the two defaults differ by construction)
        p = [resp("a"), resp("a"), resp("b"), resp("b"), resp("c")]
        r = decide(p, iid, d="b", bg="b")
        self.assertEqual((r["VV/VDF"], r["BE-G/VDF"]), ("a", "b"))

    def test_single_value_item_returns_the_value(self) -> None:
        for verified in (True, False):
            r = decide([resp("a", verified), resp("a")], d=None, bg=None)
            self.assertEqual((r["MAJ"], r["VV/VDF"], r["BE-G/VDF"], r["D"], r["BE-G"]), ("a",) * 5)

    def test_membership_compares_normalised_values(self) -> None:
        p = [resp("Paris"), resp("Paris"), {"parsed": "paris", "audit": SUP}]
        r = decide(p, d="Paris", bg="paris")
        self.assertEqual(r["W"], ["paris"])
        self.assertEqual(r["VV_VDF_branch"], "maj_verified")   # MAJ "Paris" is in W through norm_obj


class F1Sequence(unittest.TestCase):
    @staticmethod
    def rows(b: int, c: int, both_right: int, both_wrong: int = 0) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        mk = lambda i, maj, m: {"id": f"r{i}", "set": "P", "decisive": 1, "MAJ": maj, V.VV_VDF: m, V.BG_VDF: m, "D": maj,
                                "F": 0, "fhat_pairs": 0, "majority_tied": 0, "source": "popqa",
                                "VV": m, "BE-G": m, "VV_VDF_branch": "x", "BG_VDF_branch": "x"}
        n = 0
        for _ in range(b):
            out.append(mk(n, 0, 1)); n += 1
        for _ in range(c):
            out.append(mk(n, 1, 0)); n += 1
        for _ in range(both_right):
            out.append(mk(n, 1, 1)); n += 1
        for _ in range(both_wrong):
            out.append(mk(n, 0, 0)); n += 1
        return out

    def test_step1_rejects_then_step2_runs(self) -> None:
        r = V.f1_sequence(self.rows(87, 4, 372), V.VV_VDF, 0, 42)
        self.assertTrue(r["H1a"]["reject"])
        self.assertEqual(r["H1a"]["reading"], "better")
        self.assertTrue(r["H3a"]["tested"])
        self.assertEqual((r["H3a"]["c"], r["H3a"]["n_R"]), (4, 376))
        self.assertTrue(r["H3a"]["reject"])
        self.assertAlmostEqual(r["H3a"]["cp_upper_97_5"], 0.0270129, places=6)   # the selector study's bound
        self.assertTrue(r["sequence_completed"])

    def test_step1_fails_so_step2_is_not_tested(self) -> None:
        r = V.f1_sequence(self.rows(5, 4, 372, 5), V.VV_VDF, 0, 42)
        self.assertFalse(r["H1a"]["reject"])
        self.assertFalse(r["H3a"]["tested"])
        self.assertIsNone(r["H3a"]["reject"])
        self.assertEqual(r["H3a"]["reading"], "not tested (sequence stopped)")
        self.assertFalse(r["sequence_completed"])

    def test_worse_than_maj_stops_the_sequence(self) -> None:
        r = V.f1_sequence(self.rows(4, 40, 100), V.VV_VDF, 0, 42)
        self.assertTrue(r["H1a"]["reject"])
        self.assertEqual(r["H1a"]["reading"], "worse")
        self.assertFalse(r["H3a"]["tested"])

    def test_step2_tested_but_not_rejected(self) -> None:
        # 11 harms among 376 right majorities: c_max at n_R = 376 is 10
        r = V.f1_sequence(self.rows(87, 11, 365), V.VV_VDF, 0, 42)
        self.assertTrue(r["H3a"]["tested"])
        self.assertEqual(r["H3a"]["c_max_that_rejects"], 10)
        self.assertFalse(r["H3a"]["reject"])
        self.assertFalse(r["sequence_completed"])

    def test_cmax_at_376_is_ten(self) -> None:
        self.assertEqual(V.h3a_block(self.rows(0, 0, 376), V.VV_VDF)["c_max_that_rejects"], 10)


class DesignSet(unittest.TestCase):
    def test_hash_and_size(self) -> None:
        self.assertEqual(len(V.DESIGN_SET), 15)
        self.assertEqual(V.design_set_sha256(), V.DESIGN_SET_SHA256)

    def test_analyse_excludes_the_design_set(self) -> None:
        rows = F1Sequence.rows(10, 1, 40)
        rows[0]["id"] = V.DESIGN_SET[0]            # one b-item is a design-set item
        res = V.analyse(rows, 0, 42, {"J": False, "ORC": False}, None)
        self.assertEqual(res["F1_without_design_set"]["n_in_P_decisive"], 1)
        self.assertEqual(res["F1_without_design_set"]["H1a"]["b"], 9)
        self.assertEqual(res["F1"]["H1a"]["b"], 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
