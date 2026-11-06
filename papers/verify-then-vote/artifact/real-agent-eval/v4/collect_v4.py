#!/usr/bin/env python3
"""
Eval v4 collection (PREREGISTRATION.md §7, §11.1). Fork of ../v3/collect_v3.py.

Same concurrency and arrival recording as v3:
  - all 5 agents per item dispatched concurrently (one thread each) in an order shuffled
    by random.Random(dispatch_seed), dispatch seed 20261101; items run sequentially in
    frozen `order`;
  - one process-wide lock+counter (the sequencer) assigns `arrival_seq` when a response
    body has been fully read;
  - wall/monotonic timestamps, Ollama timing metadata, /api/ps samples, errors.

v4 changes (preregistered):
  - system prompt SYSTEM_PROMPT_V4 = benchmark/manifest.json["system_prompt_v4"]
    (the v3 system prompt + the final `ANSWER: <value>` line instruction); the user
    prompt is the item's `prompt` field verbatim (it already ends with the per-type
    ANSWER-line instruction: letter / SUPPORTED-REFUTED / name);
  - options temperature 0.7, num_predict 1024, seed 42; timeout 900 s;
  - a failed request is retried up to 2 times with the same seed; its arrival_seq is the
    successful attempt's (failed attempts get no seq and are kept in `attempts`); after
    3 failures the answer is missing (error set, arrival_seq assigned at final failure);
  - start-up checks (abort on any failure): FREEZE.json hashes; model digests equal
    v3/results/run_manifest.json; Ollama version recorded; server env read from the
    Ollama log;
  - Stage B guard: `--split conf` refuses to run unless FREEZE.json lists the sha256 of
    collect_v4.py and evaluate_v4.py and both match the files on disk.

Resumable: an item whose raw file exists is skipped (the dispatch RNG is advanced
per item of the full file in frozen order and the stored dispatch order is checked; the sequencer resumes
after the largest stored arrival_seq). Raw files are written atomically.

Outputs (per split):
  results/<split>/raw/<id>.json       full record
  results/<split>/run_manifest.json   environment, digests, seeds, hashes, sessions

Usage:
  python3 collect_v4.py --split dev                       # Stage A (all 160 dev items)
  python3 collect_v4.py --split dev --ids v4-tqa0772 ...  # subset (test)
  python3 collect_v4.py --split conf --n-items I          # Stage B (after code freeze)
"""

import argparse
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OLLAMA = "http://localhost:11434"
MODELS = ["llama3.2:3b", "mistral", "gemma2:2b", "phi3:mini", "qwen2.5:3b"]   # v3 list order
V3_MANIFEST = HERE.parent / "v3" / "results" / "run_manifest.json"
OLLAMA_LOG = Path(os.environ.get("BRAN_OLLAMA_LOG", "ollama.log"))
OPTIONS = {"temperature": 0.7, "num_predict": 1024, "seed": 42}
DISPATCH_SEED = 20261101
TIMEOUT_S = 900
MAX_ATTEMPTS = 3            # 1 + 2 retries
SPLIT_FILES = {"dev": "benchmark/items_dev.jsonl", "conf": "benchmark/items_confirmatory.jsonl"}

_seq_lock = threading.Lock()
_seq = [0]


def next_seq():
    with _seq_lock:
        s = _seq[0]
        _seq[0] += 1
        return s


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def atomic_dump(obj, path):
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# ── start-up checks ─────────────────────────────────────────────

def verify_freeze(split):
    freeze = json.load(open(HERE / "FREEZE.json"))
    bad = {p: (h, sha256_file(HERE / p)) for p, h in freeze["sha256"].items()
           if sha256_file(HERE / p) != h}
    if bad:
        sys.exit(f"ABORT: FREEZE.json hash mismatch: {bad}")
    if split == "conf":
        for f in ("collect_v4.py", "evaluate_v4.py"):
            h = freeze["sha256"].get(f)
            if h is None:
                sys.exit(f"ABORT: Stage B requires {f} to be frozen in FREEZE.json (amendment, §7 step 3.6)")
            if sha256_file(HERE / f) != h:
                sys.exit(f"ABORT: {f} differs from its FREEZE.json hash")
    return {"FREEZE.json_sha256": sha256_file(HERE / "FREEZE.json"), "verified": sorted(freeze["sha256"])}


def verify_digests():
    """Digests from /api/tags (this Ollama build's /api/show has no digest field; the
    /api/show `details` are recorded alongside) must equal the v3 run manifest."""
    v3 = json.load(open(V3_MANIFEST))["model_digests"]
    with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=10) as r:
        tags = {m["name"]: m for m in json.loads(r.read())["models"]}
    out, bad = {}, []
    for m in MODELS:
        t = tags.get(m) or tags.get(f"{m}:latest")
        if t is None:
            bad.append((m, "missing"))
            continue
        req = urllib.request.Request(f"{OLLAMA}/api/show", data=json.dumps({"model": m}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            show = json.loads(r.read())
        out[m] = {"name": t["name"], "digest": t["digest"],
                  "quantization": t["details"].get("quantization_level"),
                  "parameter_size": t["details"].get("parameter_size"),
                  "api_show_details": show.get("details"),
                  "api_show_modelfile_sha256": hashlib.sha256(show.get("modelfile", "").encode()).hexdigest(),
                  "v3_digest": v3[m]["digest"]}
        if t["digest"] != v3[m]["digest"]:
            bad.append((m, t["digest"], v3[m]["digest"]))
    if bad:
        sys.exit(f"ABORT: model digest mismatch vs v3 run manifest: {bad}")
    return out


def server_env():
    try:
        lines = [ln for ln in OLLAMA_LOG.read_text(errors="replace").splitlines() if 'msg="server config"' in ln]
        last = lines[-1] if lines else ""
        env = {k: re.search(rf"{k}:(\S*)", last).group(1) if re.search(rf"{k}:(\S*)", last) else None
               for k in ("OLLAMA_NUM_PARALLEL", "OLLAMA_MAX_LOADED_MODELS", "OLLAMA_KEEP_ALIVE",
                         "OLLAMA_FLASH_ATTENTION", "OLLAMA_KV_CACHE_TYPE", "OLLAMA_MAX_QUEUE")}
        return {"log": str(OLLAMA_LOG), "server_config_line": last, "parsed": env}
    except Exception as e:
        return {"error": repr(e)}


# ── requests ────────────────────────────────────────────────────

def _attempt(model, system, prompt, timeout):
    payload = json.dumps({"model": model, "prompt": prompt, "system": system,
                          "stream": False, "options": OPTIONS}).encode("utf-8")
    req = urllib.request.Request(f"{OLLAMA}/api/generate", data=payload,
                                 headers={"Content-Type": "application/json"})
    a = {"start_wall": time.time(), "start_mono": time.monotonic()}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        a["end_mono"], a["end_wall"] = time.monotonic(), time.time()
        a["data"] = data
        a["error"] = None if data.get("response") is not None else "no response field"
    except Exception as e:  # recorded, never silently dropped
        a["end_mono"], a["end_wall"] = time.monotonic(), time.time()
        a["data"] = None
        a["error"] = repr(e)
    return a


def generate(model, system, prompt, timeout):
    rec = {"model": model, "request_seed": OPTIONS["seed"], "attempts": []}
    for k in range(MAX_ATTEMPTS):
        a = _attempt(model, system, prompt, timeout)
        if a["error"] is None:
            rec["arrival_seq"] = next_seq()          # successful attempt's arrival
            data = a.pop("data")
            rec.update(start_wall=a["start_wall"], start_mono=a["start_mono"],
                       end_wall=a["end_wall"], end_mono=a["end_mono"])
            rec["raw_response"] = data.get("response", "")
            rec["ollama_meta"] = {x: data.get(x) for x in
                                  ["total_duration", "load_duration", "prompt_eval_count",
                                   "prompt_eval_duration", "eval_count", "eval_duration",
                                   "done_reason", "created_at"]}
            rec["error"] = None
            rec["n_attempts"] = k + 1
            rec["attempts"].append({x: a[x] for x in ("start_wall", "end_wall", "error")})
            return rec
        a.pop("data", None)
        rec["attempts"].append({x: a[x] for x in ("start_wall", "end_wall", "error")})
    rec["arrival_seq"] = next_seq()
    last = rec["attempts"][-1]
    rec.update(start_wall=rec["attempts"][0]["start_wall"], start_mono=None,
               end_wall=last["end_wall"], end_mono=None, raw_response="", ollama_meta=None,
               error=last["error"], n_attempts=MAX_ATTEMPTS)
    return rec


def ps_snapshot():
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/ps", timeout=5) as r:
            return [m["name"] for m in json.loads(r.read()).get("models", [])]
    except Exception as e:
        return [f"error:{e!r}"]


def run_item(item, system, order, timeout):
    out = [None] * len(order)
    stop = threading.Event()
    ps_samples = []

    def sampler():
        while not stop.is_set():
            ps_samples.append((round(time.time(), 3), ps_snapshot()))
            stop.wait(2.0)

    def worker(i, m):
        out[i] = generate(m, system, item["prompt"], timeout)

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
        r["list_index"] = MODELS.index(r["model"])
        r["agent"] = r["model"].replace(":", "_")
        r["elapsed_s"] = (round(r["end_mono"] - r["start_mono"], 3)
                          if r["end_mono"] is not None else None)
    return {"id": item["id"], "order": item["order"], "split": item["split"],
            "answer_format": item["answer_format"],
            "prompt_sha256": hashlib.sha256(item["prompt"].encode()).hexdigest(),
            "dispatch_order": order, "arrival_order": [r["model"] for r in recs],
            "list_order": MODELS, "responses": recs, "ollama_ps_samples": ps_samples}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "conf"], required=True)
    ap.add_argument("--n-items", type=int, help="first N items in frozen order (Stage B: I)")
    ap.add_argument("--ids", nargs="*", help="subset by id (testing; use a scratch --out)")
    ap.add_argument("--out", help="output dir (default results/<split>/)")
    ap.add_argument("--timeout", type=int, default=TIMEOUT_S)
    args = ap.parse_args()

    out_dir = Path(args.out).resolve() if args.out else HERE / "results" / args.split
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    freeze = verify_freeze(args.split)
    digests = verify_digests()
    with urllib.request.urlopen(f"{OLLAMA}/api/version", timeout=5) as r:
        version = json.loads(r.read())
    system = json.load(open(HERE / "benchmark" / "manifest.json"))["system_prompt_v4"]

    item_file = HERE / SPLIT_FILES[args.split]
    items = sorted((json.loads(l) for l in open(item_file)), key=lambda x: x["order"])
    assert [x["order"] for x in items] == list(range(len(items)))
    # dispatch order is a function of the item's position in frozen order (one shuffle
    # per item of the full file), so subsets and resumes see the same order per item
    rng = random.Random(DISPATCH_SEED)
    orders = {}
    for x in items:
        o = list(MODELS)
        rng.shuffle(o)
        orders[x["id"]] = o
    if args.n_items is not None:
        items = items[:args.n_items]
    if args.ids:
        items = [x for x in items if x["id"] in set(args.ids)]

    mf = out_dir / "run_manifest.json"
    manifest = json.load(open(mf)) if mf.exists() else {"sessions": []}
    session = {
        "started_wall": time.time(), "ollama_version": version,
        "ollama_list": subprocess.run(["ollama", "list"], capture_output=True, text=True).stdout,
        "model_digests": digests, "list_order": MODELS,
        "system_prompt_v4": system,
        "system_prompt_v4_sha256": hashlib.sha256(system.encode()).hexdigest(),
        "options": OPTIONS, "dispatch_seed": DISPATCH_SEED, "timeout_s": args.timeout,
        "max_attempts": MAX_ATTEMPTS, "split": args.split,
        "item_file": SPLIT_FILES[args.split], "item_file_sha256": sha256_file(item_file),
        "items_requested": [x["id"] for x in items] if (args.ids or args.n_items) else "all",
        "freeze": freeze, "collect_v4_py_sha256": sha256_file(__file__),
        "server_env": server_env(),
        "dispatch": "all 5 agents per item submitted concurrently (one thread each) in an order "
                    "shuffled by random.Random(dispatch_seed); items run sequentially in frozen order",
        "sequencer": "single process-wide lock+counter, incremented when the HTTP body of the "
                     "successful attempt is fully read",
        "argv": sys.argv,
    }
    manifest["sessions"].append(session)
    atomic_dump(manifest, mf)

    t0 = time.time()
    done = skipped = 0
    for i, it in enumerate(items):
        order = orders[it["id"]]
        f = raw_dir / f"{it['id']}.json"
        if f.exists():
            prev = json.load(open(f))
            if prev["dispatch_order"] != order:
                sys.exit(f"ABORT: resume dispatch-order mismatch on {it['id']}")
            _seq[0] = max(_seq[0], max(r["arrival_seq"] for r in prev["responses"]) + 1)
            skipped += 1
            continue
        raw = run_item(it, system, order, args.timeout)
        atomic_dump(raw, f)
        done += 1
        errs = sum(1 for r in raw["responses"] if r["error"])
        retries = sum(r["n_attempts"] - 1 for r in raw["responses"])
        print(f"[{i+1}/{len(items)}] {it['id']} arrival={[m.split(':')[0] for m in raw['arrival_order']]} "
              f"errors={errs} retries={retries} elapsed={time.time()-t0:.0f}s", flush=True)
    session["finished_wall"] = time.time()
    session["n_collected"], session["n_skipped_existing"] = done, skipped
    session["n_raw_files"] = len(list(raw_dir.glob("*.json")))
    atomic_dump(manifest, mf)
    print(f"done: collected={done} skipped={skipped} raw_files={session['n_raw_files']}", flush=True)


if __name__ == "__main__":
    main()
