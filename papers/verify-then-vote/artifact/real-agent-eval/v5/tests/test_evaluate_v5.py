"""Tests for evaluate_v5.py and make_results.py on SYNTHETIC records (no models, no network).

python3 -m unittest discover -s real-agent-eval/v5/tests -p "test_*v5.py"

The end-to-end tests need an overturn binary with the `corpus` identifier kind: $OVERTURN_BIN, else
overturn/target/release/overturn. They are skipped if neither runs.
"""
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import random
import tempfile
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
V5 = HERE.parent
ROOT = V5.parents[1]
sys.path.insert(0, str(V5))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(V5.parent))
sys.path.insert(0, str(V5.parent / "v3"))
import importlib.util  # noqa: E402



def jload(p):
    with open(p) as f:
        return json.load(f)

def load(name, path):
    """Import by path: v4/canon also has a make_results.py (which rewrites v4 output on import)."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


E = load("evaluate_v5", V5 / "evaluate_v5.py")
MR = load("make_results_v5", V5 / "make_results.py")
S = load("synth_v5", HERE / "synth_v5.py")

GRID = E.GRID


def find_bin():
    for b in (os.environ.get("OVERTURN_BIN"), str(ROOT / "overturn" / "target" / "release" / "overturn")):
        if b and os.path.exists(b):
            return b
    return None


BIN = find_bin()


def run_eval(d, split, out, *extra):
    argv = ["--split", split, "--synthetic-test", "--bin", BIN, "--items", str(d / "items.jsonl"),
            "--raw-dir", str(d / "raw"), "--captures", str(d / "captures.jsonl"), "--checks", str(d / "checks.jsonl"),
            "--judge", str(d / "judge.jsonl"), "--accepted-checker", (d / "checker_id").read_text().strip(),
            "--out", str(out), "--bootstrap", "300", *extra]
    return subprocess.run([sys.executable, str(V5 / "evaluate_v5.py"), *argv], capture_output=True, text=True)


def rows_of(out):
    return {r["id"]: r for r in list(csv.DictReader(io.StringIO(Path(out / "paired_decisions_v5.csv").read_text())))}


# ── unit tests (no binary) ──────────────────────────────────────

class TestStats(unittest.TestCase):
    def test_base_policy_is_v3_default(self):
        import evaluate_v3 as e3
        self.assertEqual(E.BASE_POLICY, e3.DEFAULT_POLICY)

    def test_mcnemar_matches_v3_definition(self):
        sys.path.insert(0, str(V5.parent))
        import evaluate_v2 as ev2
        for b in range(0, 25):
            for c in range(0, 25):
                self.assertAlmostEqual(E.mcnemar_p(b, c), ev2.mcnemar_exact(b, c), places=12)

    def test_newcombe_and_wilson(self):
        lo, hi = E.newcombe_paired(40, 59, 24, 76)
        self.assertLess(lo, (59 - 24) / 199)
        self.assertGreater(hi, (59 - 24) / 199)
        self.assertIsNone(E.wilson(0, 0))
        w = E.wilson(5, 10)
        self.assertAlmostEqual(w[0] + w[1], 1.0, places=12)

    def test_noninferiority_rule(self):
        mk = lambda a, b, c, d: E.paired([{"x": 1, "y": 1}] * a + [{"x": 1, "y": 0}] * b + [{"x": 0, "y": 1}] * c
                                         + [{"x": 0, "y": 0}] * d, "x", "y")
        same = E.noninferiority(mk(300, 20, 20, 60))
        self.assertTrue(same["noninferior"])
        self.assertFalse(same["superior"])
        worse = E.noninferiority(mk(300, 5, 40, 55))
        self.assertFalse(worse["noninferior"])
        self.assertFalse(worse["superiority_tested"])
        better = E.noninferiority(mk(300, 45, 10, 45))
        self.assertTrue(better["noninferior"] and better["superior"])

    def test_overturn_rates(self):
        rows = ([{"BE": 1, "MAJ": 0}] * 6 + [{"BE": 0, "MAJ": 0}] * 4 + [{"BE": 0, "MAJ": 1}] * 2
                + [{"BE": 1, "MAJ": 1}] * 18)
        o = E.overturn(rows, "BE")
        self.assertEqual((o["b"], o["c"], o["base_wrong"], o["base_right"]), (6, 2, 10, 20))
        self.assertAlmostEqual(o["p_w"], 0.6)
        self.assertAlmostEqual(o["q_r"], 0.1)
        self.assertAlmostEqual(o["net_gain"], 4 / 30)

    def test_grid(self):
        self.assertEqual(GRID, ["member/nei0.5", "member/nei0.1", "value:max/nei0.5", "value:max/nei0.1",
                                "value:pooled/nei0.5", "value:pooled/nei0.1"])
        self.assertEqual([E.changed_fields(g) for g in GRID], [0, 1, 1, 2, 1, 2])
        p = E.policy_for("BE", ["A", "B"], ["ck"], "value:pooled/nei0.1")
        self.assertEqual(p["candidate_mode"], {"mode": "value", "aggregate": "pooled"})
        self.assertEqual(p["evidence"]["support_factor"]["not_enough_info"], 0.1)
        self.assertEqual(p["evidence"]["unchecked_factor"], 0.5)
        self.assertNotIn("candidate_mode", E.policy_for("BE", ["A"], ["ck"], "member/nei0.5"))
        b0 = E.policy_for("B0", ["A", "B"], ["ck"])
        self.assertNotIn("evidence", b0)
        self.assertEqual((b0["weights"], b0["schulze_dims"], b0["tiebreak_order"]), (E.REC0_W, 23, "id"))
        eo = E.policy_for("EO", ["A"], ["ck"], "member/nei0.5")
        self.assertEqual((eo["weights"], eo["deadband_threshold"]), ([1.0, 0.0, 0.0, 0.0, 0.0], 0))
        with self.assertRaises(SystemExit):
            E.parse_config("value:sum/nei0.5")


class TestDevInformedGrid(unittest.TestCase):
    def test_full_grid(self):
        self.assertEqual(len(E.FULL_GRID), 18)
        self.assertEqual(E.FULL_GRID[:3], ["member/nei0.5", "member/nei0.1", "member/nei0"])
        self.assertEqual(E.GATED_GRID, [c + "/gated" for c in E.FULL_GRID[:9]])
        self.assertEqual(sorted(E.DEV_INFORMED + E.GRID), sorted(E.FULL_GRID))
        self.assertEqual(E.parse_config("value:pooled/nei0/gated"), ("value:pooled", 0.0, True))
        self.assertEqual(E.parse_config("member/nei0.1"), ("member", 0.1, False))
        self.assertEqual(E.changed_fields("member/nei0.5/gated"), 1)
        self.assertEqual(E.changed_fields("value:max/nei0/gated"), 3)
        for bad in ("member/nei0.2", "member/nei0.5/gate", "member/nei0.5/gated/gated"):
            with self.assertRaises(SystemExit):
                E.parse_config(bad)

    def test_policies(self):
        g = E.policy_for("BE", ["A", "B"], ["ck"], "member/nei0/gated")
        self.assertEqual(g["evidence"]["overturn_gate"], "verified")
        self.assertEqual(g["evidence"]["support_factor"]["not_enough_info"], 0.0)
        # ungated policies never carry the key, so their hashes are unchanged
        for cfg in E.FULL_GRID:
            if not cfg.endswith("/gated"):
                self.assertNotIn("overturn_gate", E.policy_for("BE", ["A"], ["ck"], cfg)["evidence"])
        self.assertEqual(E.evidence_policy(["ck"], 0.5), {
            "format": "bran-evidence-policy/1", "unchecked_factor": 0.5, "accepted_checkers": ["ck"],
            "support_factor": {"supports": 1.0, "not_enough_info": 0.5, "refutes": 0.0}})


def _gate_inp(answers, cfg="member/nei0.5/gated"):
    """--reduce input for one slot; answers = [(agent, value, conf, [labels])] with labels in
    supports | not_enough_info | refutes | None (unchecked) | "rogue" (supports, unaccepted)."""
    store = {"captures": {}, "support": {}}
    contribs = []
    for k, (agent, obj, conf, labels) in enumerate(answers):
        cid = f"c{k}"
        ev = []
        for j, lab in enumerate(labels):
            cap = f"cap{k}_{j}"
            store["captures"][cap] = {"outcome": "ok", "identifier_kind": "corpus",
                                      "canonical_url": f"corpus://x/{k}_{j}"}
            e = {"type": "CITATION", "source": cap, "weight": 1.0, "reachable": True,
                 "verification": "UNVERIFIED", "capture_ref": cap}
            if lab is not None:
                sid = f"s{k}_{j}"
                store["support"][sid] = {"status": "ok", "contribution_id": cid, "capture_id": cap,
                                         "checker": {"checker_id": "rogue" if lab == "rogue" else "ck"},
                                         "label": "supports" if lab == "rogue" else lab, "score_q": 9000}
                e["support_ref"] = sid
            ev.append(e)
        contribs.append({"id": cid, "agent_id": agent, "seq": (k + 1) * 1000, "confidence": conf, "evidence": ev,
                         "canonical_form": {"subject": "q", "predicate": "answer", "object": obj, "polarity": "AFFIRM"}})
    return {"policy": E.policy_for("BE", [c["canonical_form"]["object"] for c in contribs], ["ck"], cfg),
            "contributions": contribs, "calibration": {c["agent_id"]: 0.7 for c in contribs}, "evidence_store": store}


class TestGateMirrorUnit(unittest.TestCase):
    NEI3 = ["not_enough_info", "not_enough_info", None]

    def test_unverified_minority_never_overturns(self):
        ans = [("a1", "A", 0.45, []), ("a2", "A", 0.45, []), ("a3", "A", 0.45, []), ("a4", "B", 0.85, self.NEI3)]
        ungated = E.mirror(_gate_inp(ans, "member/nei0.5"))
        self.assertEqual(ungated["winner"], "c3")                 # the dev c-case mechanism
        self.assertIsNone(ungated["gate"])
        for cfg in E.GATED_GRID:
            m = E.mirror(_gate_inp(ans, cfg))
            self.assertIn(m["winner"], ("c0", "c1", "c2"), cfg)
            self.assertEqual((m["gate"]["stage"], m["gate"]["overturned"], m["gate"]["witnesses"]),
                             ("plurality", False, []))
        rogue = [("a1", "A", 0.45, []), ("a2", "A", 0.45, []), ("a4", "B", 0.85, ["rogue"])]
        self.assertEqual(E.mirror(_gate_inp(rogue, "member/nei0/gated"))["gate"]["stage"], "plurality")

    def test_verified_minority_overturns(self):
        nei = ["not_enough_info"] * 3
        ans = [("a1", "A", 0.85, nei), ("a2", "A", 0.85, nei), ("a3", "A", 0.85, nei), ("a4", "B", 0.45, ["supports"])]
        for cfg in E.GATED_GRID:
            m = E.mirror(_gate_inp(ans, cfg))
            self.assertEqual((m["winner"], m["gate"]["stage"], m["gate"]["overturned"]), ("c3", "verified", True), cfg)
            self.assertEqual(m["gate"]["witnesses"], ["c3"])

    def test_verified_majority_vs_verified_minority(self):
        ans = [("a1", "A", 0.65, ["supports", "supports"]), ("a2", "A", 0.65, []), ("a3", "A", 0.65, []),
               ("a4", "B", 0.65, ["supports"])]
        for cfg in E.GATED_GRID:
            m = E.mirror(_gate_inp(ans, cfg))
            self.assertEqual((m["gate"]["stage"], m["gate"]["overturned"]), ("verified", False), cfg)
        ans = [("a1", "A", 0.45, ["supports"]), ("a2", "A", 0.45, []), ("a3", "A", 0.45, []),
               ("a4", "B", 0.85, ["supports"] * 3)]
        for cfg in E.GATED_GRID:
            m = E.mirror(_gate_inp(ans, cfg))
            self.assertEqual((m["winner"], m["gate"]["overturned"]), ("c3", True), cfg)


class TestParse(unittest.TestCase):
    ITEM = S.tqa("v5-t", "B")
    POP = S.popqa("v5-p", "Ontario", ["Ontario"])

    def r(self, a=None, raw="", err=None):
        return {"agent": "x", "arrival_seq": 0, "answer_json": a, "raw_response": raw, "error": err}

    def test_parse_rule(self):
        good = {"reasoning": "r", "answer": "B", "citations": ["P1", "P1", "P2"], "confidence": "high"}
        a, why = E.parse_answer(self.ITEM, self.r(good))
        self.assertIsNone(why)
        self.assertEqual((a["citations"], a["violations"]), (["P1", "P2"], []))
        self.assertEqual(E.parse_answer(self.ITEM, self.r(raw=json.dumps(good)))[0]["answer"], "B")
        # unparsed: the answer field decides (harness rule)
        self.assertEqual(E.parse_answer(self.ITEM, self.r(dict(good, answer="Z")))[1], "answer_invalid")
        self.assertEqual(E.parse_answer(self.ITEM, self.r({"reasoning": "r"}))[1], "answer_invalid")
        self.assertEqual(E.parse_answer(self.ITEM, self.r(raw="ANSWER: B"))[1], "not_json")
        self.assertEqual(E.parse_answer(self.ITEM, dict(self.r(raw='{"a'), done_reason="length"))[1], "truncated")
        self.assertEqual(E.parse_answer(self.ITEM, self.r(good, err="timeout"))[1], "error")
        # parsed with recorded violations
        a, _ = E.parse_answer(self.ITEM, self.r(dict(good, confidence="sure", citations=["P1", "P2", "P3", "P4", 7])))
        self.assertEqual(a["confidence"], "low")
        self.assertEqual(a["citations"], ["P1", "P2", "P3"])
        self.assertEqual(set(a["violations"]), {"confidence_bad", "citation_not_string", "too_many_citations"})
        a, _ = E.parse_answer(self.ITEM, self.r({"answer": "B"}))
        self.assertEqual((a["citations"], a["confidence"]), ([], "low"))

    def test_l3_shape(self):
        r = {"agent": "x", "model": "x", "arrival_seq": 3, "mode": "grounded",
             "query_turn": {"query_used": "q"},
             "retrieval": {"record": {"results": [{"passage_key": "k1", "score_q": 1}]}, "passages": []},
             "answer_turn": {"raw_response": "{}", "error": None, "ollama_meta": {"done_reason": "stop"}}}
        f = E.flat_response(r)
        self.assertEqual((f["retrieval"]["results"][0]["passage_key"], f["closed_book"], f["query"]), ("k1", False, "q"))
        self.assertEqual(E.flat_response({"agent": "x", "arrival_seq": 0, "harness_error": "boom"})["error"], "boom")

    def test_entity(self):
        a, _ = E.parse_answer(self.POP, self.r({"reasoning": "", "answer": "  Ontario,  Canada ", "citations": [],
                                                "confidence": "low"}))
        self.assertEqual(a["answer"], "Ontario, Canada")
        self.assertTrue(E.grade_value(self.POP, a["canonical"], a["answer"]))
        self.assertEqual(E.parse_answer(self.POP, self.r({"reasoning": "", "answer": "x" * 61, "citations": [],
                                                          "confidence": "low"}))[1], "answer_invalid")


class TestMirrorUnit(unittest.TestCase):
    def test_single_value_has_no_slot(self):
        c = {"id": "a", "agent_id": "x", "seq": 0, "confidence": 0.85, "evidence": [],
             "canonical_form": {"object": "A"}}
        inp = {"policy": E.policy_for("B0", ["A"], []), "contributions": [c, dict(c, id="b", agent_id="y")],
               "calibration": {}}
        self.assertIsNone(E.mirror(inp))


# ── end to end (binary) ─────────────────────────────────────────

@unittest.skipUnless(BIN, "no overturn binary (set OVERTURN_BIN)")
class TestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="v5-e2e-"))
        cls.d = cls.tmp / "syn"
        S.main(["--out", str(cls.d), "--filler", "80", "--seed", "11", "--false-positive", "0.04"])
        cls.dev = cls.tmp / "dev"
        r = run_eval(cls.d, "dev", cls.dev)
        if r.returncode != 0:
            raise AssertionError(r.stdout + r.stderr)
        cls.ev = jload(cls.dev / "evaluation_v5.json")
        cls.rows = rows_of(cls.dev)
        cls.items = {r["id"]: r for r in list(csv.DictReader(io.StringIO(Path(cls.dev / "items_v5.csv").read_text())))}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_scenarios(self):
        sc = jload(self.d / "scenarios.json")
        n = 0
        for iid, s in sc.items():
            for k, v in s["expect"].items():
                n += 1
                if k in ("eligible", "decisive"):
                    self.assertEqual(int(self.items[iid][k]), v, (iid, k))
                elif k == "BE:all":
                    self.assertEqual([int(self.rows[iid]["G:" + g]) for g in GRID], [v] * 6, iid)
                else:
                    self.assertEqual(int(self.rows[iid][k]), v, (iid, k, s["scenario"]))
        self.assertGreater(n, 20)

    def test_wrong_majority_overturned_and_right_majority_overturned(self):
        r1 = self.rows["v5-s01-tqa-overturn-wrong"]
        self.assertEqual((r1["MAJ"], r1["BE"]), ("0", "1"))          # counts in b
        r2 = self.rows["v5-s02-fever-falsepos"]
        self.assertEqual((r2["MAJ"], r2["G:member/nei0.5"]), ("1", "0"))   # counts in c under member mode
        audit = [json.loads(l) for l in (self.dev / "overturns_v5.jsonl").read_text().splitlines()]
        o1 = next(o for o in audit if o["id"] == "v5-s01-tqa-overturn-wrong")
        # every overturn names the passage and the label that caused it
        self.assertTrue(any(c["support_label"] == "supports" and c["accepted"] for c in o1["winner_citations"]))
        for o in audit:
            self.assertTrue(o["winner_citations"] is not None and o["policy_hash"] and o["root_hash"])

    def test_binary_swap_uses_one_check(self):
        checks = [json.loads(l) for l in (self.d / "checks.jsonl").read_text().splitlines()]
        it = next(json.loads(l) for l in (self.d / "items.jsonl").read_text().splitlines() if "s04" in l)
        key = S.pk("scifact", it["id"], 0)
        mine = [c for c in checks if c["passage_key"] == key]
        self.assertEqual(len(mine), 1)                       # SUPPORTED and REFUTED share it
        self.assertEqual(mine[0]["label"], "refutes")        # raw label on the claim
        r = self.rows[it["id"]]
        self.assertEqual((r["MAJ"], r["BE"], r["BE_obj"]), ("0", "1", "REFUTED"))

    def test_integrity(self):
        ev = self.ev
        self.assertEqual(ev["mirror_check"]["mismatches"], 0)
        self.assertGreater(ev["mirror_check"]["slots_checked"], 8 * ev["eligible"] - 1)
        self.assertEqual(ev["design_v3"]["H3"]["BE"]["replay_identical"], ev["design_v3"]["H3"]["BE"]["replay_checked"])
        self.assertEqual(ev["design_v3"]["H3"]["BE"]["replay_checked"], ev["eligible"])
        for m, v in ev["prereg"]["H5"]["replay"]["identity"].items():
            self.assertTrue(v["all_identical"], m)
        self.assertEqual(len({g["policy_template_sha256"] for g in ev["BE_grid"]}), 18)
        self.assertEqual([g["config"] for g in ev["BE_grid"] if not g["dev_informed"]], GRID)
        self.assertTrue(all(g["dev_informed"] for g in ev["BE_grid"] if g["config"] not in GRID))
        self.assertEqual(ev["counts"].get("missing_capture", 0), 0)
        self.assertEqual(ev["counts"].get("missing_check", 0), 0)
        self.assertGreaterEqual(ev["counts"]["transient_check"], 1)

    def test_gated_configs(self):
        di = self.ev["dev_informed"]
        self.assertEqual(sorted(di["configs"]), sorted(E.GATED_GRID))
        for cfg, g in di["configs"].items():
            self.assertTrue(g["harm_bound_holds"], cfg)              # c_D items are F items
            self.assertLessEqual(g["c_vs_D"], di["F"], cfg)
            self.assertEqual(sum(g["stage_counts"].values()), self.ev["decisive"])
        # FRAMING §3.4 rule within gated templates
        gg = [x for x in self.ev["BE_grid"] if x["gated"]]
        best = sorted(gg, key=lambda x: (-x["b_minus_c"], x["c"], x["changed_fields"], E.FULL_GRID.index(x["config"])))
        self.assertEqual(di["selected_gated"], best[0]["config"])
        # every gated overturn is carried by a witness, in every stored output
        n = 0
        for p in (self.dev / "rust").rglob("BE_*_gated.out.json"):
            for s in jload(p)["selections"]:
                g = s.get("gate")
                if s["type"] == "CONTRADICTION":
                    self.assertIsNotNone(g, str(p))
                    if g["overturned"]:
                        self.assertIn(s["winner"], g["witnesses"], str(p))
                        n += 1
        self.assertGreater(n, 0)
        # the ungated outputs carry no gate trace
        for p in (self.dev / "rust").rglob("BE_member_nei0.5.out.json"):
            self.assertTrue(all("gate" not in s for s in jload(p)["selections"]))

    def test_selection_rule(self):
        g = [x for x in self.ev["BE_grid"] if not x["dev_informed"]]     # §5.1: original six only
        best = max(x["b_minus_c"] for x in g)
        cands = [x for x in g if x["b_minus_c"] == best]
        fewest = min(x["changed_fields"] for x in cands)
        first = [x["config"] for x in cands if x["changed_fields"] == fewest][0]
        self.assertEqual(self.ev["BE_config"], first)

    def test_h1_h2_and_rates(self):
        h1 = self.ev["design_v3"]["H1"]
        self.assertEqual(h1["b"] + h1["c"] + h1["a"] + h1["d"], self.ev["decisive"])
        self.assertAlmostEqual(h1["net_gain"], (h1["b"] - h1["c"]) / h1["n"])
        self.assertAlmostEqual(h1["p_w"], h1["b"] / h1["majority_wrong"])
        self.assertAlmostEqual(h1["q_r"], h1["c"] / h1["majority_right"])
        self.assertTrue(h1["reject"])                          # the synthetic world has a real effect
        self.assertGreater(h1["b"], h1["c"])
        self.assertIn("noninferior", self.ev["design_v3"]["H2"])
        self.assertEqual(self.ev["accuracy_decisive"]["ORC"], 1.0)
        gate = self.ev["dev_gate"]
        self.assertIn("stopping_rule", gate)
        self.assertGreaterEqual(gate["stopping_rule"]["I"], 1000)
        self.assertLessEqual(gate["stopping_rule"]["I"], 1400)

    def test_conf_reuses_frozen_config(self):
        cfg = "member/nei0.1"
        out = self.tmp / "conf"
        r = run_eval(self.d, "conf", out, "--be-config", cfg, "--be-g-config", "member/nei0.5/gated",
                     "--best-model", self.ev["BEST_agent"])
        self.assertEqual(r.returncode, 0, r.stderr)
        conf = jload(out / "evaluation_v5.json")
        self.assertEqual(conf["BE_config"], cfg)
        self.assertNotIn("dev_gate", conf)
        crow = rows_of(out)
        for iid, row in crow.items():
            self.assertEqual(row["BE"], self.rows[iid]["G:" + cfg], iid)
        md = MR.render(conf, self.ev)
        self.assertIn("SYNTHETIC", md)
        for h in ("### H1", "### H2", "### H3", "### H4", "### Reading", "## 2. Deviations"):
            self.assertIn(h, md)
        h1a = conf["prereg"]["H1"]["H1a"]
        self.assertIn(f"| H1a | BE-G vs MAJ on P | {h1a['n']} | {h1a['b']} | {h1a['c']} |", md)
        self.assertNotIn("BE vs the LLM judge J", md)              # the design's deleted H2
        self.assertIn("**(BE)**", md)

    def test_refusals(self):
        out = self.tmp / "refuse"
        r = run_eval(self.d, "conf", out)                      # conf needs frozen config + BEST
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--be-config", r.stdout + r.stderr)
        argv = [sys.executable, str(V5 / "evaluate_v5.py"), "--split", "dev", "--bin", BIN,
                "--items", str(self.d / "items.jsonl"), "--raw-dir", str(self.d / "raw"), "--out", str(out)]
        r = subprocess.run(argv, capture_output=True, text=True)   # SYNTHETIC marker without the flag
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("SYNTHETIC", r.stdout + r.stderr)
        nomark = self.tmp / "nomark"
        shutil.copytree(self.d / "raw", nomark)
        os.remove(nomark / "SYNTHETIC")
        r = subprocess.run(argv[:-4] + ["--raw-dir", str(nomark), "--out", str(out), "--synthetic-test"],
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        r = subprocess.run(argv[:-4] + ["--raw-dir", str(nomark), "--out", str(out), "--split", "conf",
                                        "--be-config", "member/nei0.1", "--be-g-config", "member/nei0.5/gated",
                                        "--best-model", "mistral"],
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        # The conf guard checks the binary against FREEZE.json first. A rebuilt binary stops there;
        # the frozen binary passes that check and the run stops at the next guard, the checker identity
        # (this call passes no --accepted-checker).
        if E.sha256_file(BIN) == jload(V5 / "FREEZE.json")["sha256"]["real-agent-eval/v5/frozen-bin/bran"]:
            self.assertIn(f"conf accepts exactly the prereg checker {E.PREREG_CHECKER}", r.stdout + r.stderr)
        else:
            self.assertIn("FREEZE", r.stdout + r.stderr)

    def test_tampered_inputs_abort(self):
        bad = self.tmp / "tamper"
        shutil.copytree(self.d, bad)
        lines = (bad / "checks.jsonl").read_text().splitlines()
        e = json.loads(lines[0])
        e["proposition_text"] += " (edited)"
        lines[0] = json.dumps(e)
        (bad / "checks.jsonl").write_text("\n".join(lines) + "\n")
        r = run_eval(bad, "dev", self.tmp / "tamper-out")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("proposition_key mismatch", r.stdout + r.stderr)
        shutil.copy(self.d / "checks.jsonl", bad / "checks.jsonl")
        lines = (bad / "captures.jsonl").read_text().splitlines()
        e = json.loads(lines[0])
        e["record"]["license_note"] = "edited"
        lines[0] = json.dumps(e)
        (bad / "captures.jsonl").write_text("\n".join(lines) + "\n")
        r = run_eval(bad, "dev", self.tmp / "tamper-out2")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("does not hash", r.stdout + r.stderr)

    def test_reducer_inputs_are_gold_blind(self):
        """Changing every gold field leaves every sealed reducer input byte-identical."""
        g = self.tmp / "gold"
        shutil.copytree(self.d, g)
        items = [json.loads(l) for l in (g / "items.jsonl").read_text().splitlines()]
        for it in items:
            it["gold"] = {"answer": "ZZZ", "aliases": ["zzz"]}
            for o in it.get("options") or []:
                o["correct"] = not o["correct"]
        with open(g / "items.jsonl", "w") as f:
            for it in items:
                f.write(json.dumps(it) + "\n")
        out = self.tmp / "gold-out"
        r = run_eval(g, "dev", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        n = 0
        # B0 and the six BE inputs; EO follows the dev-selected config, which reads gold by design
        # (LOAO inputs follow the dev-selected gated config, which also reads gold by design)
        for p in sorted(x for x in (self.dev / "rust").rglob("*.in.json") if not x.name.startswith(("EO", "LOAO_"))):
            q = out / "rust" / p.relative_to(self.dev / "rust")
            self.assertEqual(p.read_bytes(), q.read_bytes(), str(p))
            n += 1
        self.assertGreater(n, 100)


# ── preregistered analysis: unit tests (no binary) ──────────────

def _rows(spec):
    """spec: list of (count, {col: 0/1}) -> rows."""
    out = []
    for n, r in spec:
        out += [dict(r) for _ in range(n)]
    return out


class TestPreregStats(unittest.TestCase):
    def test_binom_cdf(self):
        import math
        for n, p in ((10, 0.3), (37, 0.05), (200, 0.5)):
            for k in (0, 1, n // 3, n - 1):
                ref = sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))
                self.assertAlmostEqual(E.binom_cdf(k, n, p), ref, places=10)
        self.assertEqual(E.binom_cdf(5, 5, 0.3), 1.0)

    def test_clopper_pearson(self):
        for n in (10, 45, 373):
            self.assertAlmostEqual(E.cp_upper(0, n), 1 - 0.025 ** (1 / n), places=10)   # closed form at x = 0
        self.assertEqual(E.cp_upper(7, 7), 1.0)
        self.assertIsNone(E.cp_upper(0, 0))
        ub = [E.cp_upper(c, 373) for c in range(15)]
        self.assertEqual(ub, sorted(ub))
        # the prereg (§2.2): at n_R = 373, H3a needs c <= 10
        self.assertLess(E.cp_upper(10, 373), 0.05)
        self.assertGreater(E.cp_upper(11, 373), 0.05)
        # definition: P(X <= c; n, ub) = 0.025
        self.assertAlmostEqual(E.binom_cdf(4, 120, E.cp_upper(4, 120)), 0.025, places=9)

    def test_holm_two_hypotheses_is_the_prereg_rule(self):
        grid = [0.001, 0.02, 0.025, 0.026, 0.04, 0.05, 0.051, 0.3]
        for pa in grid:
            for pb in grid:
                h = E.holm({"H1a": pa, "H1b": pb}, 0.05)
                p1, p2 = sorted((pa, pb))
                first = p1 <= 0.025
                second = first and p2 <= 0.05
                lo, hi = ("H1a", "H1b") if (pa, "H1a") <= (pb, "H1b") else ("H1b", "H1a")
                self.assertEqual((h[lo]["reject"], h[hi]["reject"]), (first, second), (pa, pb))
                self.assertAlmostEqual(h[lo]["p_holm"], min(1, 2 * p1))
                self.assertAlmostEqual(h[hi]["p_holm"], max(min(1, 2 * p1), p2))
        h = E.holm({"a": 0.01, "b": 0.02, "c": 0.04}, 0.05)
        self.assertEqual([h[k]["reject"] for k in "abc"], [True, True, True])
        h = E.holm({"a": 0.01, "b": 0.03, "c": 0.04}, 0.05)
        self.assertEqual([h[k]["reject"] for k in "abc"], [True, False, False])

    def test_gap_closed(self):
        rows = _rows([(6, {"MAJ": 0, "J": 1, "ORC": 1, "BE-G": 1}), (4, {"MAJ": 0, "J": 1, "ORC": 1, "BE-G": 0}),
                      (10, {"MAJ": 1, "J": 1, "ORC": 1, "BE-G": 1})])
        g = E.gap_closed(rows, ["BE-G"], ["J", "ORC"], 400, 42)
        self.assertAlmostEqual(g["BE-G"]["J"]["G"], 0.6)
        lo, hi = g["BE-G"]["J"]["bootstrap_ci95"]
        self.assertTrue(lo <= 0.6 <= hi)
        same = _rows([(5, {"MAJ": 1, "J": 1, "ORC": 1, "BE-G": 1}), (5, {"MAJ": 0, "J": 0, "ORC": 1, "BE-G": 0})])
        g2 = E.gap_closed(same, ["BE-G"], ["J"], 50, 42)
        self.assertTrue(g2["BE-G"]["J"]["undefined"])                # denominator 0
        self.assertEqual(g2["BE-G"]["J"]["bootstrap"]["undefined_resamples"], 50)
        self.assertIsNone(g2["BE-G"]["J"]["bootstrap_ci95"])
        # deterministic under the seed
        self.assertEqual(E.gap_closed(rows, ["BE-G"], ["J"], 200, 42), E.gap_closed(rows, ["BE-G"], ["J"], 200, 42))

    def test_h4_block(self):
        base = {"majority_tied": 0}
        rows = [dict(base, id="a", **{"BE-G": 0, "D": 1, "MAJ": 1, "F": 1, "fhat_pairs": 2}),
                dict(base, id="b", **{"BE-G": 1, "D": 0, "MAJ": 0, "F": 0, "fhat_pairs": 0}),
                dict(id="c", majority_tied=1, **{"BE-G": 0, "D": 0, "MAJ": 1, "F": 0, "fhat_pairs": 3})]
        h = E.h4_block(rows, "BE-G", "D", "F", "fhat_pairs", E.parse_rate("18/350"))
        self.assertEqual((h["c_D"], h["b_D"], h["F"], h["c_vs_MAJ"]), (1, 1, 1, 2))
        self.assertTrue(h["harm_bound_holds"])
        self.assertEqual((h["c_vs_MAJ_not_in_F"], h["c_vs_MAJ_not_in_F_tied"]), (["c"], 1))
        r = 18 / 350
        self.assertAlmostEqual(h["F_hat"], (1 - (1 - r) ** 2) + (1 - (1 - r) ** 3))
        rows[0]["F"] = 0
        self.assertFalse(E.h4_block(rows, "BE-G", "D", "F", "fhat_pairs", None)["harm_bound_holds"])

    def test_analysis_sets(self):
        tq, fv = S.tqa("v5-x", "A"), S.binary("v5-y", "fever", "SUPPORTED")
        self.assertEqual((E.analysis_set(tq, False), E.analysis_set(fv, False)), ("T", "P"))
        self.assertEqual(E.analysis_set(dict(tq, tier="tqa_stratum"), True), "T")
        self.assertEqual(E.analysis_set(dict(fv, tier="primary"), True), "P")
        for it, strict in ((dict(tq, tier="primary"), False), (dict(fv, tier="tqa_stratum"), False), (dict(fv, tier="dev"), True)):
            with self.assertRaises(SystemExit):
                E.analysis_set(it, strict)

    def test_prereg_templates(self):
        acc = [E.PREREG_CHECKER]
        self.assertEqual(E.template_sha("BE", E.PREREG_CONFIGS["BE-G"], acc), E.PREREG_TEMPLATES["BE-G"])
        self.assertEqual(E.template_sha("BE", E.PREREG_CONFIGS["BE"], acc), E.PREREG_TEMPLATES["BE"])
        self.assertEqual(E.template_sha("EO", E.PREREG_CONFIGS["BE"], acc), E.PREREG_TEMPLATES["EO"])
        self.assertEqual(E.template_sha("B0", None, acc), E.PREREG_TEMPLATES["B0"])
        # BE-G-L with the candidate local checker id (prereg §2.3 slot, "recompute after the id is final")
        self.assertEqual(E.template_sha("BE", E.PREREG_CONFIGS["BE-G"], ["41b9f3ecf79bc1917a2b661fb6f521ba"]),
                         "634eafecd1f1ff8a2df4c7c365139e19f101b9b36169a9c9f45317a672ba8cce")
        self.assertEqual(E.FHAT_RATE[E.PREREG_CHECKER], (18, 350))
        self.assertEqual(E.parse_rate("18/350")["rate"], 18 / 350)
        self.assertEqual(E.parse_rate("0.05")["rate"], 0.05)

    def test_judge_loader(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            p = tmp / "j.jsonl"
            p.write_text("\n".join(json.dumps(r) for r in (
                {"id": "a", "method": "J", "run": 0, "selected": "A"},
                {"id": "a", "method": "J", "run": 0, "dropped_agent": "x", "selected": "B"},
                {"id": "a", "method": "J", "run": 1, "selected": "A"})) + "\n")
            j = E.load_judge(str(p))
            self.assertEqual(sorted(j), [("J", 0), ("J", 1), ("J/loao", 0)])
            self.assertIn("a|x", j[("J/loao", 0)])
            E.load_judge(str(p), rename={"J": "J_local"}, out=j)
            self.assertIn(("J_local", 0), j)
            with self.assertRaises(SystemExit):
                E.load_judge(str(p), out=j)                         # duplicate rows
        finally:
            shutil.rmtree(tmp)


def _view(agent, val, conf, seq, correct, cites=()):
    return {"agent": agent, "parsed": val, "answer": val, "confidence": conf, "arrival_seq": seq, "correct": correct,
            "cites": [(c, c) for c in cites], "shown": ["k1", "k2"], "audit": [], "_id": f"{agent}-{val}"}


class TestBaselines(unittest.TestCase):
    """CV, CONF and the earliest-arrival MAJ on a hand-built item (no binary)."""

    def run_item(self, views, gold="B", judge=None):
        item = S.tqa("v5-hand", gold)
        rec = {"item": item, "parsed": views, "row": {"n_correct": sum(v["correct"] for v in views)}}
        ctx = types.SimpleNamespace(accepted=["ck"], judge=judge or {})
        E.python_methods(rec, ctx, "mistral")
        return rec["row"]

    def test_cv_conf_and_early(self):
        views = [_view("a1", "A", "low", 0, False), _view("a2", "A", "low", 1, False),
                 _view("mistral", "B", "high", 2, True, ["k1"]), _view("a4", "C", "medium", 3, False, ["k2"]),
                 _view("a5", "C", "low", 4, False)]
        r = self.run_item(views)
        # MAJ: A and C tie at 2; earliest arrival -> A
        self.assertEqual((r["majority_tied"], r["MAJ_early_obj"]), (1, "A"))
        # CV: citing answers B and C tie at 1 -> Random("v5-cv:<id>") over [B, C]
        self.assertEqual(r["CV_obj"], random.Random("v5-cv:v5-hand").choice(["B", "C"]))
        # CONF: A .45+.45 = .90, B .85, C .65+.45 = 1.10 -> C
        self.assertEqual((r["CONF_obj"], r["CONF"]), ("C", 0))
        self.assertEqual((r["BEST"], r["BEST_fallback"]), (1, 0))
        # no judge rows: J and J_local fall back to MAJ; CB-S / RS missing -> wrong
        self.assertEqual((r["J_fallback"], r["J_local_fallback"], r["CB-S"], r["CB-S_missing"], r["J_nullwrong"]), (1, 1, 0, 1, 0))

    def test_no_citers_falls_back(self):
        views = [_view("a1", "A", "high", 0, False), _view("a2", "B", "high", 1, True)]
        r = self.run_item(views)
        self.assertEqual((r["CV_fallback"], r["CV_obj"]), (1, r["MAJ_obj"]))
        # CONF tie .85 / .85 -> seeded
        self.assertEqual(r["CONF_obj"], random.Random("v5-conf:v5-hand").choice(["A", "B"]))

    def test_judges(self):
        views = [_view("a1", "A", "high", 0, False), _view("a2", "B", "high", 1, True)]
        judge = {("J", 0): {"v5-hand": {"status": "ok", "selected": "B"}},
                 ("J_local", 0): {"v5-hand": {"status": "error", "selected": None}},
                 ("CB-S", 0): {"v5-hand": {"status": "ok", "selected": "b"}},
                 ("RS", 0): {"v5-hand": {"status": "ok", "selected": "Z"}}}
        r = self.run_item(views, judge=judge)
        self.assertEqual((r["J"], r["J_fallback"], r["J_nullwrong"]), (1, 0, 1))
        self.assertEqual((r["J_local_fallback"], r["J_local_nullwrong"], r["J_local_has_row"]), (1, 0, 1))
        self.assertEqual((r["CB-S"], r["CB-S_obj"]), (1, "B"))       # graded by G-AK directly
        self.assertEqual((r["RS"], r["RS_obj"]), (0, None))


# ── preregistered analysis: end to end (binary) ─────────────────

@unittest.skipUnless(BIN, "no overturn binary (set OVERTURN_BIN)")
class TestConfPrereg(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="v5-prereg-"))
        cls.d = cls.tmp / "syn"
        S.main(["--out", str(cls.d), "--filler", "120", "--seed", "5", "--false-positive", "0.05"])
        cls.local_id = (cls.d / "local_checker_id").read_text().strip()
        cls.out = cls.tmp / "conf"
        r = run_eval(cls.d, "conf", cls.out, *cls.conf_args())
        if r.returncode != 0:
            raise AssertionError(r.stdout + r.stderr)
        cls.ev = jload(cls.out / "evaluation_v5.json")
        cls.pr = cls.ev["prereg"]
        cls.rows = rows_of(cls.out)

    @classmethod
    def conf_args(cls, local=True):
        a = ["--be-config", "member/nei0.1", "--be-g-config", "member/nei0.5/gated", "--best-model", "mistral",
             "--fhat-rate", "18/350", "--expect-judge-id", "CB-S=synthetic-cbs"]
        if local:
            a += ["--local-checks", str(cls.d / "checks_local.jsonl"), "--local-accepted-checker", cls.local_id,
                  "--local-arm", "confirmatory", "--judge-local", str(cls.d / "judge_local.jsonl"), "--local-fhat-rate", "0.08"]
        return a

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def dec(self, s):
        return [r for r in self.rows.values() if r["decisive"] == "1" and (s == "pooled" or r["set"] == s)]

    def count(self, rows, f):
        return sum(1 for r in rows if f(r))

    def test_sets_from_tiers(self):
        items = [json.loads(l) for l in (self.d / "items.jsonl").read_text().splitlines()]
        tq = sum(1 for it in items if it["source"]["key"] == "truthfulqa")
        a = self.pr["analysis_sets"]
        self.assertEqual((a["T"]["items"], a["P"]["items"]), (tq, len(items) - tq))
        self.assertEqual(set(a["T"]["by_source"]), {"truthfulqa"})
        self.assertNotIn("truthfulqa", a["P"]["by_source"])
        self.assertEqual(a["P"]["decisive"] + a["T"]["decisive"], self.ev["decisive"])

    def test_h1_holm_from_rows(self):
        P = self.dec("P")
        for h, m in (("H1a", "BE-G"), ("H1b", "BE")):
            t = self.pr["H1"][h]
            b = self.count(P, lambda r: r[m] == "1" and r["MAJ"] == "0")
            c = self.count(P, lambda r: r[m] == "0" and r["MAJ"] == "1")
            self.assertEqual((t["n"], t["b"], t["c"]), (len(P), b, c), h)
            self.assertAlmostEqual(t["p_exact_mcnemar"], E.mcnemar_p(b, c))
            self.assertEqual(t["bootstrap"]["resamples"], 300)
        hm = E.holm({k: self.pr["H1"][k]["p_exact_mcnemar"] for k in ("H1a", "H1b")})
        for k in ("H1a", "H1b"):
            self.assertEqual(self.pr["H1"][k]["reject"], hm[k]["reject"])
            if self.pr["H1"][k]["reject"]:
                self.assertEqual(self.pr["H1"][k]["reading"], "better" if self.pr["H1"][k]["b"] > self.pr["H1"][k]["c"] else "worse")

    def test_h3(self):
        P, T = self.dec("P"), self.dec("T")
        a = self.pr["H3"]["H3a"]
        right = [r for r in P if r["MAJ"] == "1"]
        c = self.count(right, lambda r: r["BE-G"] == "0")
        self.assertEqual((a["n_R"], a["c"]), (len(right), c))
        self.assertAlmostEqual(a["cp_upper_97_5"], E.cp_upper(c, len(right), 0.025))
        self.assertEqual(a["reject"], a["cp_upper_97_5"] < 0.05)
        b = self.pr["H3"]["H3b"]
        self.assertEqual(b["n"], len(T))
        self.assertEqual(b["reject"], b["newcombe_ci95"][0] > -0.03)
        self.assertIn(b["reading"], ("non-inferior", "not shown", "not shown; point estimate negative"))
        self.assertIn("BE_descriptive", self.pr["H3"])

    def test_h2_fixed_sequence(self):
        h = self.pr["H2"]
        self.assertEqual((h["status"], h["confirmatory"]), ("confirmatory", True))
        a, ni, sup = h["H2a"], h["H2b_NI"], h["H2b_S"]
        self.assertTrue(a["tested"])
        self.assertEqual(a["reject"], a["p_exact_mcnemar"] <= 0.05 and a["b"] > a["c"])
        self.assertEqual(ni["tested"], a["reject"])
        self.assertEqual(ni["statistic_rejects"], ni["newcombe_ci95"][0] > -0.05)
        self.assertEqual(ni["reject"], ni["tested"] and ni["statistic_rejects"])
        self.assertEqual(sup["tested"], ni["reject"])
        self.assertLessEqual(int(sup["reject"]), int(ni["reject"]))
        P = self.dec("P")
        self.assertEqual(a["b"], self.count(P, lambda r: r["BE-G-L"] == "1" and r["MAJ"] == "0"))
        self.assertEqual(ni["c"], self.count(P, lambda r: r["J_local"] == "1" and r["BE-G-L"] == "0"))
        d = h["diagnostics"]
        self.assertTrue(d["shared_model"]["all_same_model"])          # synthetic local checker, J_local and agent: mistral
        self.assertGreater(d["self_preference"]["items"], 0)

    def test_h4(self):
        for s in ("P", "T"):
            for m, v in self.pr["H4"][s].items():
                self.assertTrue(v["harm_bound_holds"], (s, m))
                self.assertLessEqual(v["c_D"], v["F"])
                self.assertIsNotNone(v["F_hat"])
        P = self.dec("P")
        v = self.pr["H4"]["P"]["BE-G"]
        self.assertEqual(v["F"], self.count(P, lambda r: r["F"] == "1"))
        r = 18 / 350
        self.assertAlmostEqual(v["F_hat"], sum(1 - (1 - r) ** int(x["fhat_pairs"]) for x in P))
        self.assertEqual(v["c_D"], self.count(P, lambda x: x["D"] == "1" and x["BE-G"] == "0"))
        self.assertFalse(self.pr["H4"]["implementation_defect"])

    def test_references_and_baselines(self):
        r = self.pr["references"]["P"]
        self.assertEqual(r["family"], ["J", "RS", "CB-S", "CV", "CONF"])
        hm = E.holm({m: r["vs_MAJ"][m]["p_exact_mcnemar"] for m in r["family"]})
        for m in r["family"]:
            self.assertAlmostEqual(r["vs_MAJ"][m]["p_holm_ref_family"], hm[m]["p_holm"])
        self.assertEqual(r["not_run"], [])
        # CB-S graded by G-AK directly: letter items correct iff the selected letter is gold
        items = {json.loads(l)["id"]: json.loads(l) for l in (self.d / "items.jsonl").read_text().splitlines()}
        cbs = {json.loads(l)["id"]: json.loads(l) for l in (self.d / "judge.jsonl").read_text().splitlines()
               if json.loads(l)["method"] == "CB-S"}
        n = 0
        for iid, row in self.rows.items():
            if items[iid]["answer_format"] == "letter":
                self.assertEqual(row["CB-S"], str(int(cbs[iid]["selected"] == items[iid]["gold"]["answer"])), iid)
                n += 1
        self.assertGreater(n, 10)

    def test_h5_cost_replay_loao(self):
        h5 = self.pr["H5"]
        for s in ("P", "T", "pooled"):
            c = h5["cost"][s]
            hc = c["hosted_checks"]
            if c["decisions"]:
                self.assertAlmostEqual(hc["per_decision"]["model_calls"] * c["decisions"], hc["total"]["model_calls"])
            self.assertEqual(hc["total"]["checks_missing"], 0)
            for m in ("J", "RS", "CB-S", "J_local"):
                self.assertIn(m, c)
            self.assertEqual(c["CB-S"]["coverage"], 1.0)
        self.assertEqual(h5["cost"]["pooled"]["decisions"], self.count(self.rows.values(), lambda r: r["disagreement"] == "1"))
        for m, v in h5["replay"]["identity"].items():
            self.assertTrue(v["all_identical"], m)
        self.assertEqual(set(h5["replay"]["identity"]), {"BE", "BE-G", "BE-G-L"})
        loao = [json.loads(l) for l in (self.out / "loao_v5.jsonl").read_text().splitlines()]
        dis = {i for i, r in self.rows.items() if r["disagreement"] == "1"}
        self.assertEqual({o["id"] for o in loao}, dis)
        n_parsed = sum(int(self.rows[i]["n_parsed"]) for i in dis)
        self.assertEqual(len(loao), n_parsed)                          # one re-decision per dropped parsed agent
        lb = h5["replay"]["LOAO"]["BE-G"]
        self.assertEqual((lb["redecisions"], lb["model_calls"]), (n_parsed, 0))
        self.assertEqual(lb["changed_redecisions"], sum(o["changed"] for o in loao))
        lj = h5["replay"]["LOAO"]["J"]
        self.assertEqual(lj["subsample_rows"], 50)
        self.assertIsNotNone(lj["change_rate"])
        ps = jload(self.out / "planned_subsamples_v5.json")
        self.assertEqual(ps["J_LOAO"]["ids"], sorted(random.Random("v5-loao").sample(sorted(dis), 50)))
        self.assertEqual(len(ps["J_regeneration"]["ids"]), min(200, len(dis)))
        self.assertIsNotNone(h5["replay"]["J_regeneration"]["agreement"])
        self.assertEqual(len(h5["replay"]["J_local_drift"]), 1)

    def test_h5_gap_audit_following(self):
        g = self.pr["H5"]["gap_closed"]["P"]
        self.assertEqual(set(g), {"BE-G", "BE", "BE-G-L", "VV", "EO"})
        acc = self.pr["accuracy"]["P"]["decisive"]
        e = g["BE-G"]["J"]
        if not e["undefined"]:
            self.assertAlmostEqual(e["G"], (acc["BE-G"] - acc["MAJ"]) / (acc["J"] - acc["MAJ"]))
        a = self.pr["H5"]["audit"]["pooled"]
        ov = self.count(self.rows.values(), lambda r: r["disagreement"] == "1" and r["BE-G_overturned"] == "1")
        self.assertEqual(a["BE-G_overturns"], ov)
        self.assertGreater(ov, 0)
        self.assertGreaterEqual(a["passages"]["median"], 1)
        mf = self.pr["H5"]["majority_following"]["P"]
        mw = [r for r in self.dec("P") if r["MAJ"] == "0" and r["J_fallback"] == "0"]
        self.assertEqual(mf["J"]["follows_majority"], self.count(mw, lambda r: r["J_obj"] == r["MAJ_obj"]))
        ws = [json.loads(l) for l in (self.out / "witness_sample_v5.jsonl").read_text().splitlines()]
        self.assertTrue(ws)
        for w in ws:
            self.assertNotIn("gold", json.dumps(w))
            self.assertIsNone(w["label_for_human"])

    def test_sensitivity_and_figures(self):
        se = self.pr["sensitivity"]
        P = self.dec("P")
        nopop = [r for r in P if r["source"] != "popqa"]
        self.assertEqual(se["popqa_excluded"]["H1a"]["n"], len(nopop))
        self.assertEqual(se["MAJ_earliest_arrival_ties"]["H1a"]["baseline"], "MAJ_early")
        self.assertIn("H2b_NI", se["null_judge_scored_wrong"])
        fig = jload(self.out / "figures_v5.json")
        self.assertEqual(set(fig), {"overturn_chart", "gap_closed", "cost_vs_replay"})
        meth = [x["method"] for x in fig["cost_vs_replay"]["P"]]
        for m in ("BE-G", "BE", "BE-G-L", "J", "CB-S", "J_local", "CV", "CONF"):
            self.assertIn(m, meth)
        be_g = next(x for x in fig["cost_vs_replay"]["P"] if x["method"] == "BE-G")
        self.assertEqual(be_g["replay"]["rate"], 1.0)

    def test_templates_recorded(self):
        t = self.pr["policy_template_sha256"]
        self.assertEqual(t["BE-G-L"], E.template_sha("BE", "member/nei0.5/gated", [self.local_id]))
        self.assertNotEqual(t["BE-G-L"], t["BE-G"])
        self.assertFalse(self.pr["template_check"]["against_prereg"])   # synthetic checker
        self.assertEqual(self.pr["template_check"]["mismatches"], [])

    def test_render(self):
        md = MR.render(self.ev)
        for h in ("### H1", "### H3", "### H2", "### H4", "### §2.4", "### Reading", "## 2. Deviations",
                  "## 3. Descriptive", "Status: **confirmatory**", "Holm", "Clopper", "Gap-closed", "leave-one-agent-out"):
            self.assertIn(h, md)
        self.assertNotIn("## 4. Dev gate", md)
        self.assertLess(md.index("## 1. Preregistered"), md.index("## 2. Deviations"))
        self.assertLess(md.index("## 2. Deviations"), md.index("## 3. Descriptive"))
        for x in MR.reading(self.pr):
            self.assertIn(x, md)

    def test_refusals(self):
        bad = [
            (["--be-config", "member/nei0.1", "--best-model", "mistral"], "--be-g-config"),
            (["--be-config", "member/nei0.1", "--be-g-config", "member/nei0.5", "--best-model", "mistral"], "gated"),
            (self.conf_args(local=False) + ["--local-arm", "confirmatory"], "needs --local-checks"),
            (self.conf_args(local=False)[:-1] + ["CB-S=other"], "judge_id"),
            (self.conf_args() + ["--expect-template", "BE-G-L=" + "0" * 64], "policy_template_sha256 mismatch"),
            (self.conf_args(local=False) + ["--local-checks", str(self.d / "checks_local.jsonl")], "--local-accepted-checker"),
        ]
        for k, (args, msg) in enumerate(bad):
            r = run_eval(self.d, "conf", self.tmp / f"refuse{k}", *args)
            self.assertNotEqual(r.returncode, 0, args)
            self.assertIn(msg, r.stdout + r.stderr, args)

    def test_exploratory_local_and_dev_mode(self):
        out = self.tmp / "dev"
        r = run_eval(self.d, "dev", out, "--local-checks", str(self.d / "checks_local.jsonl"),
                     "--local-accepted-checker", self.local_id)
        self.assertEqual(r.returncode, 0, r.stderr)
        ev = jload(out / "evaluation_v5.json")
        h2 = ev["prereg"]["H2"]
        self.assertEqual((h2["status"], h2["confirmatory"]), ("exploratory", False))
        self.assertEqual(h2["H2b_NI"]["tested"], False)                 # no J_local rows
        self.assertEqual(ev["prereg"]["methods"]["BE-G"], ev["dev_informed"]["selected_gated"])
        md = MR.render(ev)
        self.assertIn("DEV", md)
        self.assertIn("## 4. Dev gate", md)
        self.assertIn("not run as confirmatory", md)


if __name__ == "__main__":
    unittest.main()
