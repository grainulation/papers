#!/usr/bin/env python3
"""Tests for the v6 wrappers' guards and the pure parts of qualify_v6.py. No Ollama, no hosted call, no model.
Every subprocess below must stop before contacting Ollama or the claude CLI.

Run: python -I real-agent-eval/v6/tests/test_wrappers_v6.py
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import List, Tuple

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
V6 = HERE.parent
ROOT = V6.parents[1]
PY = sys.executable  # use the interpreter running this test suite
sys.path.insert(0, str(V6))


def run(script: str, *args: str, env=None) -> Tuple[int, str]:
    r = subprocess.run([PY, "-I", str(V6 / script), *args], capture_output=True, text=True, cwd=ROOT, timeout=300, env=dict(os.environ, **(env or {})))
    return r.returncode, r.stdout + r.stderr


class CollectGuards(unittest.TestCase):
    def test_out_under_v5_aborts(self) -> None:
        rc, out = run("collect_v6.py", "--split", "dev", "--out", "real-agent-eval/v5/results/x")
        self.assertNotEqual(rc, 0)
        self.assertIn("not under", out)

    def test_out_is_mandatory(self) -> None:
        rc, out = run("collect_v6.py", "--split", "dev")
        self.assertNotEqual(rc, 0)
        self.assertIn("explicit --out", out)

    def test_audit_out_must_be_under_v6_results(self) -> None:
        rc, out = run("collect_v6.py", "audit", "--out", "real-agent-eval/v5/results/conf")
        self.assertNotEqual(rc, 0)
        self.assertIn("not under", out)

    def test_build_dense_and_mixed_fleet_refused(self) -> None:
        self.assertNotEqual(run("collect_v6.py", "build-dense", "--out", "real-agent-eval/v6/results/x")[0], 0)
        rc, out = run("collect_v6.py", "--split", "dev", "--out", "real-agent-eval/v6/results/x", "--mixed-fleet", "--run")
        self.assertNotEqual(rc, 0)
        self.assertIn("mixed-fleet", out)

    def test_without_run_it_plans_then_refuses_and_never_creates_the_out_dir(self) -> None:
        rc, out = run("collect_v6.py", "--split", "dev", "--out", "real-agent-eval/v6/results/_dryrun_guard_test")
        self.assertEqual(rc, 2)
        self.assertIn("REFUSED: pass --run", out)
        self.assertIn("slot_inheritance", out)
        self.assertFalse((V6 / "results" / "_dryrun_guard_test").exists())

    def test_conf_dry_run_reports_the_missing_freeze(self) -> None:
        rc, out = run("collect_v6.py", "--split", "conf", "--n-items", "1100", "--out", "real-agent-eval/v6/results/_dryrun_guard_test")
        self.assertEqual(rc, 2)
        if not (V6 / "FREEZE.json").exists():
            self.assertIn("[FAIL] freeze", out)

    def test_run_with_failing_offline_checks_aborts_before_ollama(self) -> None:
        if (V6 / "FREEZE.json").exists():
            self.skipTest("v6 is frozen")
        rc, out = run("collect_v6.py", "--split", "conf", "--n-items", "1100", "--out", "real-agent-eval/v6/results/_dryrun_guard_test", "--run")
        self.assertNotEqual(rc, 0)
        self.assertIn("start-up checks failed", out)
        self.assertNotIn("ollama_live", out)

    def test_offline_digest_reader_matches_the_v3_run_manifest(self) -> None:
        import collect_v6 as C6
        v3 = json.loads((V6.parent / "v3" / "results" / "run_manifest.json").read_text())["model_digests"]
        for tag in ("llama3.2:3b", "mistral", "gemma2:2b", "phi3:mini", "qwen2.5:3b"):
            got = C6.local_manifest_digest(tag if tag != "mistral" else "mistral")
            if got is None:
                self.skipTest(f"{tag} not installed")
            self.assertEqual(got, v3[tag]["digest"], tag)

    def test_models_and_overrides(self) -> None:
        import collect_v6 as C6
        self.assertEqual(C6.C.MODELS, ["falcon3:3b", "olmo2:7b", "exaone3.5:7.8b", "nemotron-mini:4b", "granite3.3:2b"])
        self.assertEqual(C6.C.V3_MANIFEST, V6 / "pool_manifest.json")
        self.assertEqual(C6.C.FREEZE, V6 / "FREEZE.json")
        self.assertIn("real-agent-eval/v6/collect_v6.py", C6.C.CONF_FROZEN)
        self.assertEqual(len(C6.C.MODELS), len(C6.C_V5_MODELS))


class QualifyGuards(unittest.TestCase):
    def test_out_outside_v6_results_aborts(self) -> None:
        rc, out = run("qualify_v6.py", "--raw-dir", "real-agent-eval/v6/results/dev/raw", "--out", "/tmp/q.json")
        self.assertNotEqual(rc, 0)
        self.assertIn("not under", out)

    def test_without_run_refuses(self) -> None:
        rc, out = run("qualify_v6.py", "--raw-dir", "real-agent-eval/v6/results/dev/raw", "--out", "real-agent-eval/v6/results/dev/qualification_guard_probe.json")
        self.assertEqual(rc, 2)
        self.assertIn("REFUSED", out)
        self.assertFalse((V6 / "results" / "dev" / "qualification_guard_probe.json").exists())

    def test_pure_criteria(self) -> None:
        import qualify_v6 as Q
        ok = Q.agent_verdict(160, 4, 4, 0, 156, 60)
        self.assertTrue(ok["pass_all"])
        self.assertFalse(Q.agent_verdict(160, 8, 0, 0, 152, 100)["Q1"]["pass"])        # 8/160 = 0.05 is not < 0.05
        self.assertFalse(Q.agent_verdict(160, 0, 8, 0, 160, 100)["Q2"]["pass"])        # truncation 0.05
        self.assertFalse(Q.agent_verdict(160, 0, 0, 1, 160, 100)["Q2"]["pass"])        # one prompt + 512 > 4096
        self.assertFalse(Q.agent_verdict(160, 0, 0, 0, 160, 39)["Q3"]["pass"])         # 39/160 < 0.25
        self.assertTrue(Q.agent_verdict(160, 0, 0, 0, 160, 40)["Q3"]["pass"])          # 40/160 = 0.25
        pool = Q.pool_verdict(160, 160, 48, 10)
        self.assertTrue(pool["Q4"]["pass"])                                            # 0.30 is not < 0.30
        self.assertFalse(Q.pool_verdict(160, 160, 47, 10)["Q4"]["pass"])
        self.assertTrue(Q.pool_verdict(160, 160, 50, 10)["Q5"]["pass"])                # m = 0.20
        self.assertFalse(Q.pool_verdict(160, 160, 50, 9)["Q5"]["pass"])
        d = Q.pool_verdict(160, 120, 40, 20)
        self.assertTrue(d["Q4"]["pass"] and d["Q4"]["value_decisive_over_all_items"] < 0.30)   # the two yield definitions can differ

    def test_best_follows_v5_expression(self) -> None:
        import qualify_v6 as Q
        correct = {"olmo2_7b": 100, "falcon3_3b": 100, "granite3.3_2b": 90}
        best, tied = Q.best_agent(correct)
        self.assertEqual(best, "falcon3_3b")                    # max(sorted(ids)): alphabetically first of the tie
        self.assertEqual(tied, ["falcon3_3b", "olmo2_7b"])


class PostCollectAndEvaluate(unittest.TestCase):
    def test_post_collect_without_run_prints_plan_and_refuses(self) -> None:
        rc, out = run("post_collect_v6.py", "--steps", "checks,judges")
        self.assertEqual(rc, 2)
        self.assertIn("no hosted call is made", out)
        self.assertIn("--max-usd 60", out)
        self.assertIn("v6/results/conf", out.replace("\\", "/"))
        self.assertNotIn("v5/results", out.replace("real-agent-eval/v5/benchmark", ""))

    def test_post_collect_rejects_unknown_step(self) -> None:
        self.assertNotEqual(run("post_collect_v6.py", "--steps", "nope")[0], 0)

    def test_evaluate_conf_needs_a_frozen_v6(self) -> None:
        if (V6 / "FREEZE.json").exists():
            self.skipTest("v6 is frozen")
        rc, out = run("evaluate_v6.py", "--split", "conf", "--bin", "x", "--items", "x", "--raw-dir", "x", "--out", "/tmp/never")
        self.assertNotEqual(rc, 0)
        self.assertIn("FREEZE.json does not exist", out)

    def test_evaluate_out_under_v5_refused(self) -> None:
        rc, out = run("evaluate_v6.py", "--split", "conf", "--out", "real-agent-eval/v5/results/conf/eval2")
        self.assertNotEqual(rc, 0)
        self.assertIn("must not be under", out)

    def test_evaluate_reproduce_needs_out(self) -> None:
        rc, out = run("evaluate_v6.py", "--reproduce-v5")
        self.assertNotEqual(rc, 0)
        self.assertIn("needs --out", out)

    def test_evaluate_selftest_passes_through(self) -> None:
        rc, out = run("evaluate_v6.py", "--selftest")
        self.assertEqual(rc, 0, out[-500:])

    def test_futility_refuses_wrong_number_of_records(self) -> None:
        rc, out = run("futility_v6.py", "--items", str(V6.parent / "v5/benchmark/items_dev.jsonl"), "--raw-dir", str(V6 / "tests"),
                      "--captures", "x", "--checks", "x", "--out", "/tmp/never_fut")
        self.assertNotEqual(rc, 0)


class LocalArmAndAliases(unittest.TestCase):
    def test_local_checks_without_run_is_offline_and_refuses(self) -> None:
        v5 = V6.parent / "v5" / "results" / "conf"
        if not (v5 / "checks_plan.jsonl").exists():
            self.skipTest("v5 plan not present")
        rc, out = run("local_checks_v6.py", "--plan", str(v5 / "checks_plan.jsonl"), "--cache", str(v5 / "evidence-cache"),
                      "--out", "real-agent-eval/v6/results/_lc_guard_test/checks_local.jsonl",
                      env={"BRAN_OLLAMA_LOG": str(HERE / "missing-server.log")})
        self.assertEqual(rc, 2)
        self.assertIn("REFUSED: pass --run", out)
        # Server configuration participates in identity. A fresh public checkout
        # has no original machine log, so it must report the mismatch and refuse,
        # not pretend to have the historical checker identity.
        self.assertRegex(out, r"\[FAIL\] checker_id recomputed offline: [0-9a-f]{32}")
        self.assertIn("Failing checks:", out)
        self.assertFalse((V6 / "results" / "_lc_guard_test").exists())

    def test_local_checks_out_must_be_under_v6_results(self) -> None:
        rc, out = run("local_checks_v6.py", "--plan", "x", "--cache", "x", "--out", "/tmp/c.jsonl")
        self.assertEqual(rc, 2)
        self.assertIn("[FAIL] out under v6/results", out)

    def test_be_g_l_template_is_derivable_offline(self) -> None:
        import evaluate_v6 as X
        self.assertEqual(X.be_g_l_template(), "c9ecf2fbcd964e15c782ec54a804997d5b575c3ca42de5bc76cd997c43a503c2")
        self.assertEqual(X.MINICHECK_ID, "98751cc07911d57a1586848dfb8c4e7b")

    def test_agreement_counts(self) -> None:
        import vdf_v6 as V
        mk = lambda i, a, b, dis, dec, ca, cb: {"id": i, "set": "P", "decisive": dec, "disagreement": dis, V.VV_VDF_L: ca, V.VV_VDF: cb,
                                               V.VV_VDF_L + "_obj": a, V.VV_VDF + "_obj": b}
        rows = [mk("a", "x", "x", 1, 1, 1, 1), mk("b", "x", "y", 1, 1, 1, 0), mk("c", "x", "y", 1, 1, 0, 1), mk("d", "z", "z", 0, 0, 1, 1)]
        r = V.agreement(rows, V.VV_VDF_L, V.VV_VDF, "P")
        self.assertEqual((r["all_eligible"]["n"], r["all_eligible"]["agree"]), (4, 2))
        self.assertEqual((r["disagreement_items"]["n"], r["disagreement_items"]["agree"]), (3, 1))
        self.assertEqual((r["decisive_paired"]["b"], r["decisive_paired"]["c"]), (1, 1))

    def test_alias_builder_deterministic_and_guarded(self) -> None:
        out = "real-agent-eval/v6/results/_alias_guard_test.jsonl"
        rc, text = run("build_alias_items_v6.py", "--out", out)
        self.assertEqual(rc, 0, text[-400:])
        rep = json.loads(text)
        self.assertEqual((rep["popqa_items_changed"], rep["aliases_added"]), (214, 747))
        self.assertEqual(rep["aliases_sha256"], "77d1fce09c137647eea4a12b85dfc574d493e86fe9f79f2d1d653bb8b4ca2174")
        first = (ROOT / out).read_bytes()
        run("build_alias_items_v6.py", "--out", out)
        self.assertEqual((ROOT / out).read_bytes(), first)
        (ROOT / out).unlink()
        rc, text = run("build_alias_items_v6.py", "--out", "/tmp/never_alias.jsonl")
        self.assertNotEqual(rc, 0)
        rc, text = run("build_alias_items_v6.py", "--out", "real-agent-eval/v5/results/x.jsonl")
        self.assertNotEqual(rc, 0)
        self.assertFalse((V6.parent / "v5" / "results" / "x.jsonl").exists())

    def test_alias_builder_refuses_a_different_alias_list(self) -> None:
        import build_alias_items_v6 as B
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "aliases.json"
            p.write_text("{}")
            with self.assertRaises(SystemExit):
                B.build(str(V6.parent / "v5" / "benchmark" / "items_confirmatory.jsonl"), str(p))


if __name__ == "__main__":
    unittest.main(verbosity=2)
