"""Fast checks of power_v5.py (the full reproduction is `python3 power/power_v5.py`, ~80 s)."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "power"))
import power_v5 as P  # noqa: E402


class TestPower(unittest.TestCase):
    def test_anchor_and_planning(self):
        self.assertEqual(P.n_star(0.25, 0.10), 207)          # v4 Table 1
        d, psi = P.b_c(0.35, 0.4, 0.10)
        self.assertAlmostEqual(d, 0.075)
        self.assertAlmostEqual(psi, 0.205)
        self.assertEqual(P.n_star(psi, d), 302)
        self.assertEqual(P.n_star(0.25, 0.075), 368)
        self.assertEqual(math.ceil(368 / 0.45), 818)

    def test_stopping_rule(self):
        s = P.stopping_rule(0.10, 0.45)
        self.assertEqual((s["psi_used"], s["N_star"], s["I_unclamped"], s["I"]), (0.25, 368, 818, 1000))
        self.assertEqual(P.stopping_rule(0.25, 0.30)["I"], 1227)
        self.assertEqual(P.stopping_rule(0.30, 0.30)["I"], 1400)
        self.assertTrue(P.stopping_rule(0.30, 0.30)["exceeds_cap"])
        self.assertEqual(P.stopping_rule(0.25, 0.0)["I"], 1400)

    def test_h2_normal(self):
        self.assertAlmostEqual(P.ni_power_normal(368, 0.15), 0.70, places=2)
        self.assertAlmostEqual(P.ni_power_normal(368, 0.10), 0.86, places=2)
        self.assertAlmostEqual(P.ni_power_normal(450, 0.15), 0.78, places=2)
        self.assertAlmostEqual(P.ni_power_normal(450, 0.10), 0.92, places=2)

    def test_stage_a(self):
        a = P.stage_a()
        self.assertEqual(a["all"]["decisive"], 80)
        self.assertAlmostEqual(a["all"]["maj_correct_expected"], 51.87, places=2)
        self.assertEqual((a["all"]["strict_wrong"], a["all"]["ties_at_top"], a["all"]["ge3_on_one_wrong_value"],
                          a["all"]["all_wrong_items"]), (20, 16, 14, 29))
        self.assertEqual(a["strict_wrong_minority"]["_single_agent_minority"], 19)
        with self.assertRaises(SystemExit):
            P.stage_a("/x/v4/results/conf/responses_v4.jsonl")


if __name__ == "__main__":
    unittest.main()
