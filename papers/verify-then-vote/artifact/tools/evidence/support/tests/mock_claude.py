#!/usr/bin/env python3
"""Stub for the `claude` CLI used by the unit tests. Behaviour is chosen by
MOCK_CLAUDE_MODE; every invocation appends {argv, stdin} to MOCK_CLAUDE_LOG."""
import json
import os
import sys
import time

if "--version" in sys.argv:
    print("%s (Claude Code)" % os.environ.get("MOCK_CLAUDE_VERSION", "9.9.9"))
    sys.exit(0)

mode = os.environ.get("MOCK_CLAUDE_MODE", "supports")
stdin = sys.stdin.read()
log = os.environ.get("MOCK_CLAUDE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"argv": sys.argv[1:], "stdin": stdin}) + "\n")

model = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else "unknown"
so = {"label": "supports", "confidence": 9000}
subtype, is_error, rc = "success", False, 0
if mode == "refutes":
    so = {"label": "refutes", "confidence": 8000}
elif mode == "bad_label":
    so = {"label": "SUPPORTED", "confidence": 9000}
elif mode == "extra_key":
    so = {"label": "supports", "confidence": 9000, "reason": "x"}
elif mode == "float_conf":
    so = {"label": "supports", "confidence": 0.9}
elif mode == "bool_conf":
    so = {"label": "supports", "confidence": True}
elif mode == "range_conf":
    so = {"label": "supports", "confidence": 10001}
elif mode == "no_structured":
    so = None
elif mode == "wrong_model":
    model = "claude-other-model"
elif mode == "is_error":
    subtype, is_error, rc = "error_max_budget_usd", True, 1
elif mode == "refusal":
    print(json.dumps([{"type": "result", "subtype": "success", "is_error": True, "stop_reason": "refusal",
                       "result": "API Error: safeguards flagged this message\n\nRequest ID: req_1"}]))
    sys.exit(1)
elif mode == "not_json":
    print("this is not json")
    sys.exit(0)
elif mode == "sleep":
    time.sleep(5)

events = [
    {"type": "system", "subtype": "init", "model": model},
    {"type": "assistant", "message": {"model": model, "content": []}},
    {"type": "result", "subtype": subtype, "is_error": is_error, "total_cost_usd": 0.001,
     "result": json.dumps(so) if so is not None else "I think it supports it.",
     **({"structured_output": so} if so is not None else {})},
]
print(json.dumps(events))
sys.exit(rc)
