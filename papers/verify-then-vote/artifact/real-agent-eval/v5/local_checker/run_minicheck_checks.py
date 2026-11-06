#!/usr/bin/env python3
"""EXPLORATORY, outside the preregistration. MiniCheck fails the preregistered three-way macro-F1
criterion by construction (binary checker) and meets every supports criterion
(tools/evidence/support/validation/MINICHECK_RESULTS.md).

Runs the MiniCheck checker (tools/evidence/support/minicheck_check.py, checker_id 98751cc0…) on the
4,742 cited (proposition, passage) pairs of the v5 confirmatory check plan
(results/conf/checks_plan.jsonl, rows whose reasons include "cited"). It uses the same sealed
captures (results/conf/evidence-cache) and the same run_checks_v5.run_checks path as the hosted run.
Sequential (workers 1). No hosted call.

Writes, in this directory:
  checks_minicheck.jsonl     evaluate_v5 --checks format (one row per planned check)
  check_calls_minicheck.jsonl  per-call log
  support-cache/             sealed MiniCheck outputs

Run: tools/corpus/.venv/bin/python -I real-agent-eval/v5/local_checker/run_minicheck_checks.py [--limit N]
"""
import argparse
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SUP = os.path.join(ROOT, "tools", "evidence", "support")
sys.path[:0] = [SUP, os.path.dirname(SUP)]
import run_checks_v5 as RC  # noqa: E402
import minicheck_check as MC  # noqa: E402

CONF = os.path.join(ROOT, "real-agent-eval", "v5", "results", "conf")
EXPECT = "98751cc07911d57a1586848dfb8c4e7b"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)
    plan = [r for r in RC.read_jsonl(os.path.join(CONF, "checks_plan.jsonl")) if "cited" in r["reasons"]]
    if a.limit:
        plan = plan[:a.limit]
    c = MC.MiniCheckChecker()
    if c.checker_id != EXPECT:
        raise SystemExit("ABORT: checker_id %s != validated %s" % (c.checker_id, EXPECT))
    rows, _, wall = RC.run_checks(plan, c, os.path.join(CONF, "evidence-cache"), os.path.join(HERE, "support-cache"),
                                  1, 2, None, os.path.join(HERE, "check_calls_minicheck.jsonl"))
    RC.write_jsonl(os.path.join(HERE, "checks_minicheck.jsonl"), rows)
    print(json.dumps({"checker_id": c.checker_id, "planned": len(plan), "written": len(rows),
                      "status": dict(Counter(r["status"] for r in rows)),
                      "labels": dict(Counter(r["label"] or "-" for r in rows)), "wall_s": round(wall, 1)}, indent=1))
    return 0 if len(rows) == len(plan) else 2


if __name__ == "__main__":
    sys.exit(main())
