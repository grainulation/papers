#!/usr/bin/env python3
"""Stub for the `claude` CLI used by the judge unit tests. MOCK_JUDGE_MODE picks
the behaviour; every call appends {argv, stdin} to MOCK_JUDGE_LOG. Default
answers the first enum value of the --json-schema (or "Paris" for free text)."""
import json
import os
import sys
import time

if "--version" in sys.argv:
    print("9.9.9 (Claude Code)")
    sys.exit(0)

mode = os.environ.get("MOCK_JUDGE_MODE", "first")
stdin = sys.stdin.read()
log = os.environ.get("MOCK_JUDGE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"argv": sys.argv[1:], "stdin": stdin}) + "\n")
schema = json.loads(sys.argv[sys.argv.index("--json-schema") + 1])
ans_s = schema["properties"]["answer"]
model = sys.argv[sys.argv.index("--model") + 1]
enum = ans_s.get("enum")
answer = enum[0] if enum else "Paris"
if mode == "last" and enum:
    answer = enum[-1]
so = {"answer": answer, "confidence": 8000}
subtype, is_error, rc, stop = "success", False, 0, "end_turn"
if mode == "outside":
    so = {"answer": "ZZZ", "confidence": 8000}
elif mode == "extra_key":
    so["why"] = "x"
elif mode == "float_conf":
    so["confidence"] = 0.8
elif mode == "too_long":
    so["answer"] = "x" * 61
elif mode == "wrong_model":
    model = "claude-other"
elif mode == "is_error":
    subtype, is_error, rc = "error_max_budget_usd", True, 1
elif mode == "refusal":
    print(json.dumps([{"type": "result", "subtype": "success", "is_error": True, "stop_reason": "refusal",
                       "result": "API Error: safeguards flagged this message\n\nRequest ID: req_%d" % time.time_ns()}]))
    sys.exit(1)
elif mode == "not_json":
    print("nope")
    sys.exit(0)
elif mode == "sleep":
    time.sleep(5)
print(json.dumps([
    {"type": "system", "subtype": "init", "model": model, "session_id": str(time.time_ns())},
    {"type": "assistant", "message": {"model": model, "content": []}},
    {"type": "result", "subtype": subtype, "is_error": is_error, "stop_reason": stop, "total_cost_usd": 0.0123,
     "usage": {"input_tokens": 1500, "output_tokens": 20, "cache_read_input_tokens": 0},
     "duration_ms": 1234, "result": json.dumps(so), "structured_output": so},
]))
sys.exit(rc)
