#!/usr/bin/env python3
"""
Eval v3 collection: same prompts / system prompt / options as ../collect.py,
but the 5 agents per question are dispatched CONCURRENTLY (in a shuffled,
seed-recorded submission order) and every response records:

  - wall-clock start/end (time.time()) and monotonic start/end
  - Ollama's own timing metadata (total/load/prompt_eval/eval durations)
  - arrival_seq: a monotone sequence number assigned by a single sequencer
    (one lock, one counter) at the moment the HTTP response is fully read.

arrival_seq is global across the whole run; arrival_rank is 0..k-1 within
the question. Claim extraction is ../collect.py:extract_claims_from_text,
imported unchanged, so claims are produced exactly as in the original.

Outputs:
  results/raw/<qid>.json   full record (dispatch order, timings, metadata, raw text)
  results/<qid>.json       v1-compatible response list, ordered by arrival
  results/run_manifest.json  run configuration, model digests, server config
"""

import argparse
import json
import random
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import collect as c0  # noqa: E402  (original collection harness, unchanged)

RESULTS = HERE / "results"
RAW = RESULTS / "raw"
OLLAMA = "http://localhost:11434"

_seq_lock = threading.Lock()
_seq = [0]


def next_seq():
    with _seq_lock:
        s = _seq[0]
        _seq[0] += 1
        return s


def generate(model, prompt, seed, timeout):
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "system": c0.SYSTEM_PROMPT,
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": 1024, "seed": seed},
    }).encode("utf-8")
    req = urllib.request.Request(f"{OLLAMA}/api/generate", data=payload,
                                 headers={"Content-Type": "application/json"})
    rec = {"model": model, "request_seed": seed}
    rec["start_wall"] = time.time()
    rec["start_mono"] = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        rec["end_mono"] = time.monotonic()
        rec["end_wall"] = time.time()
        rec["arrival_seq"] = next_seq()
        rec["raw_response"] = data.get("response", "")
        rec["ollama_meta"] = {k: data.get(k) for k in
                              ["total_duration", "load_duration", "prompt_eval_count",
                               "prompt_eval_duration", "eval_count", "eval_duration",
                               "done_reason", "created_at"]}
        rec["error"] = None
    except Exception as e:  # recorded, never silently dropped
        rec["end_mono"] = time.monotonic()
        rec["end_wall"] = time.time()
        rec["arrival_seq"] = next_seq()
        rec["raw_response"] = ""
        rec["ollama_meta"] = None
        rec["error"] = repr(e)
    return rec


def ps_snapshot():
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/ps", timeout=5) as r:
            return [m["name"] for m in json.loads(r.read()).get("models", [])]
    except Exception as e:
        return [f"error:{e!r}"]


def run_question(q, models, rng, base_seed, timeout):
    order = list(models)
    rng.shuffle(order)
    out = [None] * len(order)
    stop = threading.Event()
    ps_samples = []

    def sampler():
        while not stop.is_set():
            ps_samples.append((round(time.time(), 3), ps_snapshot()))
            stop.wait(2.0)

    def worker(i, m):
        out[i] = generate(m, q["question"], base_seed, timeout)

    st = threading.Thread(target=sampler, daemon=True)
    st.start()
    threads = []
    for i, m in enumerate(order):          # submitted in shuffled order
        t = threading.Thread(target=worker, args=(i, m))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    stop.set()
    st.join()

    recs = sorted(out, key=lambda r: r["arrival_seq"])
    for rank, r in enumerate(recs):
        r["arrival_rank"] = rank
        r["dispatch_index"] = order.index(r["model"])
        r["list_index"] = list(models).index(r["model"])
        r["agent"] = r["model"].replace(":", "_")
        r["elapsed_s"] = round(r["end_mono"] - r["start_mono"], 3)
    return {"id": q["id"], "question": q["question"], "dispatch_order": order,
            "arrival_order": [r["model"] for r in recs],
            "list_order": list(models), "responses": recs,
            "ollama_ps_samples": ps_samples}


def to_v1(raw):
    resps = []
    for r in raw["responses"]:
        if not r["raw_response"]:
            continue   # original collect.py also dropped empty responses
        resps.append({
            "agent": r["agent"], "model": r["model"],
            "raw_response": r["raw_response"],
            "claims": c0.extract_claims_from_text(r["raw_response"], r["model"]),
            "calibration": 0.7,
            "response_time_s": r["elapsed_s"],
            "arrival_seq": r["arrival_seq"], "arrival_rank": r["arrival_rank"],
            "list_index": r["list_index"], "dispatch_index": r["dispatch_index"],
            "start_wall": r["start_wall"], "end_wall": r["end_wall"],
        })
    return resps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dispatch-seed", type=int, default=20261021)
    ap.add_argument("--request-seed", type=int, default=42)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--questions", nargs="*")
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--out", default=str(HERE / "results"),
                    help="output dir (default results/); replicate runs use results_rep<N>/")
    args = ap.parse_args()
    global RESULTS, RAW
    RESULTS = Path(args.out).resolve()
    RAW = RESULTS / "raw"

    RAW.mkdir(parents=True, exist_ok=True)
    questions = json.load(open(HERE.parent / "questions.json"))
    if args.questions:
        questions = [q for q in questions if q["id"] in args.questions]
    models = c0.DEFAULT_MODELS

    with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=5) as r:
        tags = {m["name"]: m for m in json.loads(r.read())["models"]}
    with urllib.request.urlopen(f"{OLLAMA}/api/version", timeout=5) as r:
        version = json.loads(r.read())
    digests = {}
    for m in models:
        t = tags.get(m) or tags.get(f"{m}:latest")
        digests[m] = {"name": t["name"], "digest": t["digest"],
                      "quantization": t["details"].get("quantization_level"),
                      "parameter_size": t["details"].get("parameter_size")}
    manifest = {
        "started_wall": time.time(), "ollama_version": version,
        "ollama_list": subprocess.run(["ollama", "list"], capture_output=True, text=True).stdout,
        "model_digests": digests, "list_order": models,
        "system_prompt": c0.SYSTEM_PROMPT,
        "options": {"temperature": 0.7, "num_predict": 1024, "seed": args.request_seed},
        "dispatch_seed": args.dispatch_seed, "timeout_s": args.timeout,
        "dispatch": "all 5 agents per question submitted concurrently (one thread each) "
                    "in an order shuffled by random.Random(dispatch_seed); questions run sequentially",
        "sequencer": "single process-wide lock+counter, incremented when the HTTP body is fully read",
        "server_env_note": "OLLAMA_NUM_PARALLEL / OLLAMA_MAX_LOADED_MODELS read from server log at start; see README",
    }
    rng = random.Random(args.dispatch_seed)
    t0 = time.time()
    for i, q in enumerate(questions):
        f = RAW / f"{q['id']}.json"
        if args.skip_existing and f.exists():
            rng.shuffle(list(models))  # keep the RNG stream aligned on resume
            prev = json.load(open(f))
            _seq[0] = max(_seq[0], max(r["arrival_seq"] for r in prev["responses"]) + 1)
            print(f"[{i+1}/{len(questions)}] SKIP {q['id']}", flush=True)
            continue
        raw = run_question(q, models, rng, args.request_seed, args.timeout)
        json.dump(raw, open(f, "w"), indent=2)
        json.dump(to_v1(raw), open(RESULTS / f"{q['id']}.json", "w"), indent=2)
        errs = sum(1 for r in raw["responses"] if r["error"])
        print(f"[{i+1}/{len(questions)}] {q['id']} dispatch={raw['dispatch_order']} "
              f"arrival={raw['arrival_order']} errors={errs} "
              f"elapsed={time.time()-t0:.0f}s", flush=True)
    manifest["finished_wall"] = time.time()
    manifest["n_questions"] = len(questions)
    mf = RESULTS / "run_manifest.json"
    if args.questions and mf.exists():
        mf = RESULTS / f"run_manifest_partial_{int(t0)}.json"
    json.dump(manifest, open(mf, "w"), indent=2)


if __name__ == "__main__":
    main()
