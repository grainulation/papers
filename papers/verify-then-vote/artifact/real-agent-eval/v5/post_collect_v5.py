#!/usr/bin/env python3
"""
Eval v5 post-collection driver (PREREGISTRATION.md §8, steps 3-6): everything between the end of
collection and the single `evaluate_v5.py --split conf` run. Model-gold-blind: it reads parsed
answers to find disagreement items but writes no grade.

Steps (each is resumable; the judge and support stores cache every sealed call)
  checks    captures, plan (gold scope decisive, gold-restrict fever,scifact), hosted checks with
            --expect-checker, gold availability
  inputs    judge_inputs.jsonl; disagreement ids (>= 2 parsed, >= 2 distinct values); the
            J-regeneration (Random("v5-jregen"), 200) and LOAO (Random("v5-loao"), 50) subsamples
  judges    J and RS (judge-store), CB-S (judge-store-cbs) on every disagreement item
  regen     J again on the 200 regeneration items, in a fresh store (run 1)
  loao      J on the 50 LOAO items with each agent dropped, one fresh store per agent
  local     J_local (mistral, exploratory) on every disagreement item
  rows      judge.jsonl (J, RS, CB-S, regeneration run 1, LOAO rows) and judge_local.jsonl

All hosted calls use the pinned Claude Code CLI (§5, CLI pin) with auto-update off.

Usage
  python3 post_collect_v5.py [--steps checks,inputs,judges,regen,loao,local,rows]
"""

import argparse
import json
import os
import random
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import evaluate_v5 as E  # noqa: E402

CLI_PIN = "2.1.307"
CLAUDE = Path(os.environ.get("BRAN_CLAUDE_BIN", "claude"))
VENV_PY = Path(os.environ.get("BRAN_PYTHON", sys.executable))
OUT = HERE / "results/conf"
ITEMS = HERE / "benchmark/items_confirmatory.jsonl"
STEPS = ["checks", "inputs", "judges", "regen", "loao", "local", "rows"]
N_ITEMS = 1100


def sh(argv, log=None):
    print("+ " + " ".join(map(str, argv)), file=sys.stderr, flush=True)
    env = dict(os.environ, DISABLE_AUTOUPDATER="1")
    if log:
        with open(log, "a") as fh:
            r = subprocess.run(list(map(str, argv)), cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT)
    else:
        r = subprocess.run(list(map(str, argv)), cwd=ROOT, env=env)
    if r.returncode:
        raise SystemExit(f"ABORT: exit {r.returncode}: {argv[:3]}")


def read_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def write_jsonl(p, rows):
    with open(p, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def step_checks():
    rc = [VENV_PY, ROOT / "tools/evidence/support/run_checks_v5.py"]
    a = ["--split", "conf"]
    sh(rc + ["captures"] + a, OUT / "captures.log")
    sh(rc + ["plan"] + a + ["--gold-scope", "decisive", "--gold-restrict", "fever,scifact"], OUT / "plan.log")
    sh(rc + ["--claude-bin", CLAUDE, "check"] + a + ["--workers", "6", "--retries", "2", "--max-usd", "60",
                                                    "--expect-checker", E.PREREG_CHECKER], OUT / "checks_run.log")
    sh(rc + ["gold-avail"] + a, OUT / "gold_avail.log")


def step_inputs():
    sh([VENV_PY, HERE / "collect_v5.py", "judge-inputs", "--out", OUT])
    items = E.load_items(str(ITEMS))
    dis = []
    for f in sorted((OUT / "raw").glob("*.json")):
        raw = E.jload(f)
        vals = [v["parsed"] for v in (E.response_view(items[raw["id"]], r) for r in raw["responses"])
                if v["parsed"] is not None]
        if len(vals) >= 2 and len(set(vals)) >= 2:
            dis.append(raw["id"])
    dis.sort()
    (OUT / "disagreement_ids.txt").write_text("".join(i + "\n" for i in dis))
    keep = set(dis)
    inputs = [r for r in read_jsonl(OUT / "judge_inputs.jsonl") if r["item_id"] in keep]
    write_jsonl(OUT / "judge_inputs_disagreement.jsonl", inputs)
    jregen = sorted(random.Random("v5-jregen").sample(dis, min(200, len(dis))))
    loao = sorted(random.Random("v5-loao").sample(dis, min(50, len(dis))))
    (OUT / "jregen_ids.txt").write_text("".join(i + "\n" for i in jregen))
    (OUT / "loao_ids.txt").write_text("".join(i + "\n" for i in loao))
    print(json.dumps({"raw": N_ITEMS, "disagreement": len(dis), "jregen": len(jregen), "loao": len(loao)}))


def _judge(method, inputs, store, log, extra=()):
    sh(["python3", "-I", ROOT / "tools/judge/judge.py", "--claude-bin", CLAUDE, "run", "--method", method,
        "--items", ITEMS, "--inputs", inputs, "--out", store, "--workers", "6", *extra], log)


def step_judges():
    inp = OUT / "judge_inputs_disagreement.jsonl"
    _judge("J", inp, OUT / "judge-store", OUT / "judge_J.log")
    _judge("RS", inp, OUT / "judge-store", OUT / "judge_RS.log")
    sh(["python3", "-I", ROOT / "tools/judge/closed_book.py", "--claude-bin", CLAUDE, "run", "--items", ITEMS,
        "--ids", OUT / "disagreement_ids.txt", "--out", OUT / "judge-store-cbs", "--workers", "6"],
       OUT / "judge_CBS.log")


def step_regen():
    keep = set((OUT / "jregen_ids.txt").read_text().split())
    write_jsonl(OUT / "judge_inputs_jregen.jsonl",
                [r for r in read_jsonl(OUT / "judge_inputs_disagreement.jsonl") if r["item_id"] in keep])
    _judge("J", OUT / "judge_inputs_jregen.jsonl", OUT / "judge-store-jregen", OUT / "judge_J_regen.log")


def loao_agents():
    rows = read_jsonl(OUT / "judge_inputs_disagreement.jsonl")
    return sorted({a["agent_id"] for r in rows for a in r["agents"]})


def step_loao():
    keep = set((OUT / "loao_ids.txt").read_text().split())
    rows = [r for r in read_jsonl(OUT / "judge_inputs_disagreement.jsonl") if r["item_id"] in keep]
    for ag in loao_agents():
        p = OUT / f"judge_inputs_loao_{ag}.jsonl"
        write_jsonl(p, [dict(r, agents=[a for a in r["agents"] if a["agent_id"] != ag]) for r in rows])
        _judge("J", p, OUT / f"judge-store-loao-{ag}", OUT / "judge_J_loao.log")


def step_local():
    sh([VENV_PY, ROOT / "tools/judge/local_judge.py", "run", "--method", "J", "--items", ITEMS,
        "--inputs", OUT / "judge_inputs_disagreement.jsonl", "--out", OUT / "judge-store-local"],
       OUT / "judge_local.log")


def _rows(cmd, store, out, extra=()):
    sh([VENV_PY, *cmd, "--store", store, *extra, "--out-file", out])
    return read_jsonl(out)


def step_rows():
    rc = [ROOT / "tools/evidence/support/run_checks_v5.py", "judge-rows"]
    tmp = OUT / "judge_rows_tmp.jsonl"
    rows = _rows(rc, OUT / "judge-store", tmp)
    rows += _rows([ROOT / "tools/judge/closed_book.py", "rows"], OUT / "judge-store-cbs", tmp)
    rows += [dict(r, run=1) for r in _rows(rc, OUT / "judge-store-jregen", tmp)]
    for ag in loao_agents():
        rows += [dict(r, dropped_agent=ag) for r in _rows(rc, OUT / f"judge-store-loao-{ag}", tmp)]
    tmp.unlink()
    write_jsonl(OUT / "judge.jsonl", rows)
    if (OUT / "judge-store-local").exists():
        _rows([ROOT / "tools/judge/local_judge.py", "rows"], OUT / "judge-store-local", OUT / "judge_local.jsonl")
    print(json.dumps({"judge_rows": len(rows)}))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", default=",".join(STEPS))
    args = ap.parse_args(argv)
    v = subprocess.run([str(CLAUDE), "--version"], capture_output=True, text=True,
                       env=dict(os.environ, DISABLE_AUTOUPDATER="1")).stdout
    if not v.startswith(CLI_PIN + " "):
        raise SystemExit(f"ABORT: pinned CLI {CLAUDE} reports {v!r}")
    n = len(list((OUT / "raw").glob("*.json")))
    if n != N_ITEMS:
        raise SystemExit(f"ABORT: {n} raw records, expected {N_ITEMS} (collection incomplete)")
    fns = {s: globals()["step_" + s] for s in STEPS}
    for s in args.steps.split(","):
        print(f"== {s}", file=sys.stderr, flush=True)
        fns[s]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
