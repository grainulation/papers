#!/usr/bin/env python3
"""Unit tests for pooled_h3a_v6.py (PREREGISTRATION.md 2.3). Pure arithmetic; no data files needed.

Run:  tools/corpus/.venv/bin/python -I real-agent-eval/v6/tests/test_pooled_h3a_v6.py
"""
import sys
import unittest
from pathlib import Path
from typing import List, Tuple

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import pooled_h3a_v6 as H  # noqa: E402


class PooledExact(unittest.TestCase):
    def test_12_plus_13_of_376_each_rejects(self) -> None:
        r = H.pooled_exact(12, 376, 13, 376)
        self.assertTrue(r["reject"])
        self.assertLess(r["cp_upper_97_5"], 0.05)
        self.assertEqual(r["c6_allowed"], 13)

    def test_12_plus_14_of_376_each_does_not_reject(self) -> None:
        r = H.pooled_exact(12, 376, 14, 376)
        self.assertFalse(r["reject"])
        self.assertGreaterEqual(r["cp_upper_97_5"], 0.05)

    def test_v5_alone_is_the_published_bound(self) -> None:
        self.assertAlmostEqual(H.PW.cp_upper(12, 376, 0.025), 0.0551, places=4)

    def test_allowed_c6_grid_matches_prereg_9_3(self) -> None:
        grid: List[Tuple[int, int]] = [(300, 10), (340, 12), (376, 13), (410, 15), (450, 16)]
        for n6, want in grid:
            self.assertEqual(H.pooled_exact(12, 376, 0, n6)["c6_allowed"], want, n6)


class PooledRobust(unittest.TestCase):
    def test_u5_is_0587(self) -> None:
        self.assertAlmostEqual(H.PW.cp_upper(12, 376, 0.0125), 0.0587, places=4)

    def test_robust_cmax_at_376_is_7(self) -> None:
        self.assertTrue(H.pooled_robust(12, 376, 7, 376)["holds_robustly"])
        self.assertFalse(H.pooled_robust(12, 376, 8, 376)["holds_robustly"])
        self.assertEqual(H.pooled_robust(12, 376, 0, 376)["c6_allowed"], 7)

    def test_robust_is_stricter_than_exact(self) -> None:
        e, r = H.pooled_exact(12, 376, 10, 376), H.pooled_robust(12, 376, 10, 376)
        self.assertTrue(e["reject"])
        self.assertFalse(r["holds_robustly"])


class Bootstrap(unittest.TestCase):
    def test_interval_contains_the_point_and_is_reproducible(self) -> None:
        items = [(1, 1, 0, 1)] * 12 + [(0, 1, 0, 1)] * 364 + [(0, 0, 1, 1)] * 13 + [(0, 0, 0, 0)] * 100
        a = H.cluster_bootstrap(items, 500, 42)
        b = H.cluster_bootstrap(items, 500, 42)
        self.assertEqual(a, b)
        lo, hi = a["ci95"]
        point = (12 + 13) / (376 + 377)
        self.assertLess(lo, point)
        self.assertGreater(hi, point)


class CrossPool(unittest.TestCase):
    def test_hybrid_interval_brackets_the_difference(self) -> None:
        lo, hi = H.diff_ci(0.05, [0.03, 0.08], 0.03, [0.01, 0.06])
        self.assertLess(lo, 0.02)
        self.assertGreater(hi, 0.02)

    def test_metrics_counts(self) -> None:
        m = H.metrics(526, 91, 12, 150, 376)
        self.assertAlmostEqual(m["net"], (91 - 12) / 526)
        self.assertAlmostEqual(m["q_r"], 12 / 376)
        self.assertAlmostEqual(m["p_w"], 91 / 150)


if __name__ == "__main__":
    unittest.main(verbosity=2)
