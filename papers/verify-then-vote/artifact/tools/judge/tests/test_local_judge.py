"""Unit tests for tools/judge/local_judge.py against an in-process mock Ollama.
Run: python3 -I -m unittest discover -s tools/judge/tests -t tools/judge"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
JUDGE_DIR = os.path.dirname(HERE)
sys.path.insert(0, JUDGE_DIR)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(JUDGE_DIR), "evidence", "support", "tests"))
import judge  # noqa: E402
import local_judge as LJ  # noqa: E402
import local_check as LC  # noqa: E402
from canonical import canonical_bytes, record_id  # noqa: E402
from mock_ollama import DIGEST, MockOllama, gen_ok  # noqa: E402
from test_judge import BIN, ENT, ITEMS, MC, agent, mc_input  # noqa: E402

SERVER = {k: "x" for k in LC.SERVER_KEYS}


def pin_for(mock, **over):
    p = dict(LJ.load_local_pin(), endpoint=mock.endpoint, timeout_s=20)
    p.update(over)
    return p


def answer_echo(body):
    """Pick the first allowed enum value from the request's schema (or 'Lyon' for free text)."""
    sch = body["format"]["properties"]["answer"]
    ans = sch["enum"][0] if "enum" in sch else "Lyon"
    return gen_ok(json.dumps({"answer": ans, "confidence": 7000}), prompt_eval_count=3000, eval_count=15)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ljudge-")
        self.store = judge.JudgeStore(os.path.join(self.tmp, "store"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestIdentity(Base):
    def test_ids(self):
        with MockOllama() as m:
            j = LJ.LocalJudge("J", pin=pin_for(m), server=SERVER)
            r = LJ.LocalJudge("RS", pin=pin_for(m), server=SERVER)
            hosted = judge.Judge("J", claude_bin="/nonexistent")
            self.assertNotEqual(j.judge_id, r.judge_id)
            self.assertNotEqual(j.judge_id, hosted.judge_id)
            self.assertEqual(set(j.ident), set(hosted.ident))
            self.assertEqual(j.ident["prompt_template_sha256"], hosted.ident["prompt_template_sha256"])
            self.assertEqual(j.ident["model_digest"], "sha256:" + DIGEST)
            self.assertEqual(j.ident["decoding"]["num_ctx"], 8192)
            self.assertEqual(j.ident["decoding"]["temperature_x1000"], 0)
            self.assertEqual(judge.compute_judge_id(j.ident), j.judge_id)
            self.assertEqual(j.block(None)["runtime_version"], "ollama/0.17.7")
            m.version = "0.18.0"
            self.assertNotEqual(LJ.LocalJudge("J", pin=pin_for(m), server=SERVER).judge_id, j.judge_id)

    def test_digest_mismatch(self):
        with MockOllama(digest="1" * 64) as m:
            with self.assertRaises(LC.OllamaError):
                LJ.LocalJudge("J", pin=pin_for(m), server=SERVER)


class TestDecide(Base):
    def test_J_request_and_record(self):
        with MockOllama() as m:
            m.responder = answer_echo
            j = LJ.LocalJudge("J", pin=pin_for(m), server=SERVER)
            out = judge.decide(j, self.store, MC, mc_input())
            (body,) = m.generate_calls()
            call = j.build(judge.item_view(MC), mc_input())
            self.assertEqual(body["prompt"], call["prompt"])
            self.assertEqual(body["format"], call["schema"])
            self.assertEqual(body["system"], judge.load_template("J")["system"])
            self.assertEqual(body["options"], LJ.load_local_pin()["options"])
            self.assertEqual(out["status"], "ok")
            self.assertEqual(out["record"]["answer"], "A")  # first of the sorted allowed values
            self.assertEqual(out["record"]["judge"]["runtime_version"], "ollama/0.17.7")
            self.assertEqual(out["record"]["judge"]["judge_id"], j.judge_id)
            self.assertEqual(record_id(out["record"]), out["record_id"])
            canonical_bytes(out["record"])
            # cached: no second call; offline replay works
            again = judge.decide(j, self.store, MC, mc_input(), offline=True)
            self.assertEqual(again["record_id"], out["record_id"])
            self.assertEqual(len(m.generate_calls()), 1)

    def test_regenerate_logs_agreement(self):
        with MockOllama() as m:
            m.responder = answer_echo
            j = LJ.LocalJudge("J", pin=pin_for(m), server=SERVER)
            judge.decide(j, self.store, MC, mc_input())
            r = judge.decide(j, self.store, MC, mc_input(), regenerate=True)
            self.assertTrue(r["agree"])
            self.assertEqual(r["regen"]["raw_output_sha256"], r["authoritative"]["raw_output_sha256"])

    def test_RS_free_text_and_rows(self):
        with MockOllama() as m:
            m.responder = answer_echo
            rs = LJ.LocalJudge("RS", pin=pin_for(m), server=SERVER)
            inp = {"format": judge.INPUT_FORMAT, "item_id": ENT["id"], "agents": [agent("a", "Lyon"), agent("b", "Paris")]}
            out = judge.decide(rs, self.store, ENT, inp)
            self.assertEqual(out["record"]["answer"], "Lyon")
            rows = LJ.judge_rows(self.store.root)
            self.assertEqual(rows, [{"id": ENT["id"], "method": "RS", "run": 0, "status": "ok", "selected": "Lyon",
                                     "input_tokens": 3000, "output_tokens": 15, "usd": 0.0,
                                     "wall_ms": rows[0]["wall_ms"]}])

    def test_statuses(self):
        opts = LJ.load_local_pin()["options"]
        call = judge.build_J(judge.item_view(MC), mc_input(), judge.load_template("J"))
        v = judge.make_validator(call)
        st = lambda d: LJ.parse_judge_response(d, "mistral:latest", opts, v)["status"]  # noqa: E731
        self.assertEqual(st(gen_ok('{"answer": "A", "confidence": 1}')[1]), "ok")
        self.assertEqual(st(gen_ok('{"answer": "Z", "confidence": 1}')[1]), "parse_error")
        self.assertEqual(st(gen_ok('{"answer": "A", "confidence": -1}')[1]), "parse_error")
        self.assertEqual(st(gen_ok('{"answer": "A"}')[1]), "parse_error")
        self.assertEqual(st(gen_ok('{"answer": "A", "confidence": 1}', done_reason="length")[1]), "parse_error")
        self.assertEqual(st(gen_ok('{"answer": "A", "confidence": 1}', model="qwen2.5:3b")[1]), "model_mismatch")
        self.assertEqual(st(gen_ok('{"answer": "A", "confidence": 1}', prompt_eval_count=8100)[1]), "input_too_long")

    def test_input_too_long_sealed_and_cached(self):
        with MockOllama() as m:
            m.responder = lambda b: gen_ok('{"answer": "A", "confidence": 1}', prompt_eval_count=8192,
                                           done_reason="length")
            j = LJ.LocalJudge("J", pin=pin_for(m), server=SERVER)
            out = judge.decide(j, self.store, MC, mc_input())
            self.assertEqual(out["status"], "input_too_long")
            self.assertIsNone(out["record"]["answer"])
            judge.decide(j, self.store, MC, mc_input())
            self.assertEqual(len(m.generate_calls()), 1)

    def test_transient_not_sealed(self):
        with MockOllama() as m:
            m.responder = lambda b: (500, {"error": "boom"})
            j = LJ.LocalJudge("J", pin=pin_for(m), server=SERVER)
            out = judge.decide(j, self.store, MC, mc_input())
            self.assertEqual(out["status"], "judge_error")
            self.assertIsNone(out["record_id"])

    def test_forced_no_call(self):
        with MockOllama() as m:
            j = LJ.LocalJudge("J", pin=pin_for(m), server=SERVER)
            inp = {"format": judge.INPUT_FORMAT, "item_id": BIN["id"],
                   "agents": [agent("a", "REFUTED"), agent("b", "REFUTED")]}
            out = judge.decide(j, self.store, BIN, inp)
            self.assertEqual(out["status"], "forced")
            self.assertEqual(m.generate_calls(), [])


if __name__ == "__main__":
    unittest.main()
