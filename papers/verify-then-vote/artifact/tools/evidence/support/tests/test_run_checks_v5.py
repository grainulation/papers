"""Tests for run_checks_v5.py on SYNTHETIC v5 records with the stub CLI (no models, no network).

python3 -m unittest tools.evidence.support.tests.test_run_checks_v5
"""
import importlib.util
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
SUPPORT = os.path.dirname(HERE)
ROOT = os.path.abspath(os.path.join(SUPPORT, "..", "..", ".."))
sys.path.insert(0, SUPPORT)
sys.path.insert(0, os.path.dirname(SUPPORT))
import capture  # noqa: E402
import check  # noqa: E402
import corpus_capture as CC  # noqa: E402
import propositions as PR  # noqa: E402
import run_checks_v5 as RC  # noqa: E402

MOCK = os.path.join(HERE, "mock_claude.py")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _lines(p):
    with open(p) as fh:
        return sum(1 for _ in fh)


class Synthetic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.chmod(MOCK, os.stat(MOCK).st_mode | stat.S_IXUSR)
        cls.tmp = tempfile.mkdtemp(prefix="rc5-")
        synth = _load("synth_v5", os.path.join(ROOT, "real-agent-eval", "v5", "tests", "synth_v5.py"))
        cls.data = os.path.join(cls.tmp, "synth")
        with redirect_stdout(io.StringIO()):
            synth.main(["--out", cls.data, "--filler", "12"])
        cls.EV = RC.load_evaluate()
        cls.items = cls.EV.load_items(os.path.join(cls.data, "items.jsonl"))
        cls.raws = RC.load_raws(os.path.join(cls.data, "raw"))
        cls.cache_root = os.path.join(cls.tmp, "cache")
        cache = capture.Cache(cls.cache_root)
        cls.caps = {}
        for cid, keys in RC.wanted_keys(cls.items, cls.raws, cls.EV).items():
            mem = {k: synth.text(k) for k in keys if k.startswith(cid + ":")}
            src = CC.CorpusSource(cid, "f" * 64, "test licence", passages=mem)
            for k, capid, rec in CC.capture_passages(sorted(keys), src, cache):
                cls.caps[k] = {"passage_key": k, "capture_id": capid, "record": rec}
        cls.plan, cls.summary = RC.build_plan(cls.items, cls.raws, cls.caps, cls.EV, "decisive")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_plan_is_deduplicated(self):
        keys = [p["check_key"] for p in self.plan]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(keys, sorted(keys))
        pairs = [(p["proposition_key"], p["passage_key"]) for p in self.plan]
        self.assertEqual(len(pairs), len(set(pairs)))
        for p in self.plan:
            self.assertEqual(p["check_key"], PR.check_key(p["proposition_key"], p["passage_key"]))
            self.assertEqual(p["proposition_key"], PR.proposition_key(p["proposition_text"]))
            self.assertEqual(self.caps[p["passage_key"]]["record"]["outcome"], "ok")

    def test_every_ok_citation_is_planned(self):
        planned = {p["check_key"] for p in self.plan}
        for iid, raw in self.raws.items():
            for r in raw["responses"]:
                v = self.EV.response_view(self.items[iid], r)
                for _, pk in v.get("cites") or []:
                    if self.caps[pk]["record"]["outcome"] == "ok":
                        self.assertIn(PR.check_key(v["prop"]["proposition_key"], pk), planned)

    def test_gold_checks_only_on_decisive_items_and_cover_all_shown(self):
        dec = {s["id"] for s in self.summary if s["decisive"]}
        self.assertTrue(dec)
        gold_items = {i for p in self.plan if "gold_shown" in p["reasons"] for i in p["item_ids"]}
        self.assertTrue(gold_items <= dec)
        planned = {p["check_key"] for p in self.plan}
        for iid in dec:
            item = self.items[iid]
            gp = PR.render(item, self.EV.gold_value(item))
            shown = {pk for r in self.raws[iid]["responses"] for pk in self.EV.response_view(item, r)["shown"]}
            for pk in shown:
                if self.caps[pk]["record"]["outcome"] == "ok":
                    self.assertIn(PR.check_key(gp["proposition_key"], pk), planned)

    def test_gold_restrict_drops_non_gold_passages(self):
        plan, _ = RC.build_plan(self.items, self.raws, self.caps, self.EV, "decisive", ("fever", "scifact"), {})
        for p in plan:
            src = self.items[p["item_ids"][0]]["source"]["key"]
            if src == "fever":   # no passage meta: no FEVER passage is deterministic gold
                self.assertIn("cited", p["reasons"])
        full = {p["check_key"] for p in self.plan}
        self.assertTrue({p["check_key"] for p in plan} <= full)
        tq = lambda pl: {p["check_key"] for p in pl if self.items[p["item_ids"][0]]["source"]["key"] == "truthfulqa"}  # noqa: E731
        self.assertEqual(tq(plan), tq(self.plan))

    def test_binary_values_share_one_check(self):
        for p in self.plan:
            item = self.items[p["item_ids"][0]]
            if item["source"]["key"] in PR.BINARY_SOURCES:
                self.assertEqual(p["proposition_text"], PR.item_claim(item))

    def test_run_checks_writes_evaluate_format_and_caches(self):
        log = os.path.join(self.tmp, "mock.log")
        os.environ["MOCK_CLAUDE_MODE"] = "supports"
        os.environ["MOCK_CLAUDE_LOG"] = log
        try:
            pin = check.load_pin()
            checker = check.Checker(claude_bin=MOCK, pin=pin, workdir=self.tmp)
            sub = self.plan[:15]
            rows, spent, _ = RC.run_checks(sub, checker, self.cache_root, self.cache_root, workers=3,
                                           log_path=os.path.join(self.tmp, "calls.jsonl"), progress=False)
            self.assertEqual(len(rows), len(sub))
            n_calls = _lines(log)
            self.assertGreater(n_calls, 0)
            out = os.path.join(self.tmp, "checks.jsonl")
            RC.write_jsonl(out, rows)
            loaded = self.EV.load_checks(out)        # key and proposition hashes verified
            self.assertEqual(set(loaded), {p["check_key"] for p in sub})
            for r in rows:
                self.assertEqual(r["status"], "ok")
                self.assertEqual(r["label"], "supports")
                self.assertEqual(r["checker"]["checker_id"], checker.checker_id)
                self.assertTrue(r["spans"])
                self.assertIsNotNone(r["cost_usd"])
            # second run: all cached, no new CLI calls, identical rows
            rows2, spent2, _ = RC.run_checks(sub, checker, self.cache_root, self.cache_root, workers=3,
                                             log_path=os.path.join(self.tmp, "calls.jsonl"), progress=False)
            self.assertEqual(_lines(log), n_calls)
            self.assertEqual(spent2, 0.0)
            self.assertEqual(rows, rows2)
        finally:
            os.environ.pop("MOCK_CLAUDE_MODE", None)
            os.environ.pop("MOCK_CLAUDE_LOG", None)

    def test_budget_stops_live_calls(self):
        os.environ["MOCK_CLAUDE_MODE"] = "refutes"
        try:
            pin = dict(check.load_pin())
            checker = check.Checker(claude_bin=MOCK, pin=pin, workdir=self.tmp,
                                    checker_tool_version="budget-test")   # fresh cache keys
            rows, spent, _ = RC.run_checks(self.plan[:20], checker, self.cache_root, self.cache_root, workers=1,
                                           max_usd=0.0025, log_path=os.path.join(self.tmp, "b.jsonl"), progress=False)
            self.assertLess(len(rows), 20)
            self.assertLessEqual(spent, 0.0025 + 0.001 + 1e-9)
        finally:
            os.environ.pop("MOCK_CLAUDE_MODE", None)


class Pieces(unittest.TestCase):
    def test_covers(self):
        m = {"page_id": "A_B", "sent_ids": [3, 7], "content": ""}
        self.assertTrue(RC._covers(m, "A_B", 3))
        self.assertTrue(RC._covers(m, "A_B", 7))
        self.assertFalse(RC._covers(m, "A_B", 8))
        self.assertFalse(RC._covers(m, "A_C", 4))
        self.assertFalse(RC._covers(None, "A_B", 4))

    def test_judge_rows(self):
        tmp = tempfile.mkdtemp(prefix="rc5j-")
        try:
            os.makedirs(os.path.join(tmp, "records"))
            os.makedirs(os.path.join(tmp, "index"))
            os.makedirs(os.path.join(tmp, "log"))
            recs = [("J", "i1", "ok", "B", "k1"), ("J", "i2", "forced", "A", "k2"), ("RS", "i1", "refused", None, "k3")]
            with open(os.path.join(tmp, "index", "records.jsonl"), "w") as ix:
                for n, (m, iid, st, ans, ck) in enumerate(recs):
                    rid = "r%d" % n
                    with open(os.path.join(tmp, "records", rid + ".json"), "w") as fh:
                        json.dump({"method": m, "item_id": iid, "status": st, "answer": ans, "cache_key": ck}, fh)
                    ix.write(json.dumps({"method": m, "item_id": iid, "record_id": rid}) + "\n")
            with open(os.path.join(tmp, "log", "calls.jsonl"), "w") as fh:
                fh.write(json.dumps({"cache_key": "k1", "cached": False, "cost_usd": 0.01, "duration_ms": 900,
                                     "usage": {"input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 5}}) + "\n")
                fh.write(json.dumps({"cache_key": "k1", "cached": False, "regenerate": True, "cost_usd": 0.5}) + "\n")
            rows = {(r["method"], r["id"]): r for r in RC.judge_rows(tmp)}
            self.assertEqual(rows[("J", "i1")]["selected"], "B")
            self.assertEqual(rows[("J", "i1")]["input_tokens"], 100)
            self.assertEqual(rows[("J", "i1")]["usd"], 0.01)
            self.assertEqual(rows[("J", "i2")]["selected"], "A")
            self.assertEqual(rows[("J", "i2")]["usd"], 0.0)
            self.assertIsNone(rows[("RS", "i1")]["selected"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
