#!/usr/bin/env python3
"""
Eval v5 collection: grounded agents (v3/SWARM3_DESIGN.md §3, lane L3).

Run with the corpus venv (bm25s, numpy):  tools/corpus/.venv/bin/python -I collect_v5.py ...

Per item, all 5 agents run concurrently (one thread each, submitted in an order shuffled by
random.Random(20261101), one shuffle per item of the full split file in frozen order, as v4).
Each agent thread runs its own pipeline:

  1. query turn   question only (MC options hidden), JSON {"query"} via Ollama `format`,
                  num_predict 32; the query is cut to its first 12 words.
  2. retrieve     the agent's own query, k = 5, labelled P1..P5 by rank. fever17 items use
                  BM25 (tools/corpus/retrieve.py, sealed bran-retrieval/1). SciFact items use
                  BM25 or dense nomic-embed-text by a seeded per-item rule (§3.2).
  3. answer turn  question, options and the agent's 5 passages; JSON {reasoning, answer,
                  citations, confidence} via Ollama `format` = schema/answer_v5.schema.json
                  with `answer` = the item's answer_schema and `citations.items.enum` = the
                  labels actually shown (so a citation can only name the agent's own passages);
                  num_predict 512.

Optional pre-declared fallback arm (§3.2, only if the dev gate fails): --mixed-fleet makes
2 of 5 agents per item closed-book (no query turn, no passages, citations maxItems 0),
chosen by random.Random("v5-cb:"+id) from the 10 model pairs (each model 40% in expectation).

Recording (as v4): one process-wide sequencer assigns `arrival_seq` when the answer-turn body
is fully read (query turns use a separate `query_arrival_seq` counter); wall/monotonic
timestamps; Ollama timing metadata; /api/ps samples; retries (2, same seed) with failed
attempts kept; prompt and schema hashes; the full sealed retrieval record per agent and the
content sha256 of each shown passage. Raw records carry only the agent-visible item view; no
gold-bearing field is ever read into a prompt or a raw record.

Start-up checks (abort on failure): model digests equal v3/results/run_manifest.json; corpus
index hashes equal tools/corpus/corpus_manifest.json; dense index manifest hash; if FREEZE.json
exists every hash it lists must match. `--split conf` refuses to run unless FREEZE.json exists
and lists every file in CONF_FROZEN with matching hashes (FREEZE.json keys are repo-relative).

Resumable: an item whose raw file exists is skipped (dispatch order checked, sequencers resume).

Subcommands:
  collect (default)   python collect_v5.py --split dev [--ids ...] [--out DIR]
  build-dense         embed the SciFact passages with nomic-embed-text (once)
  audit               python collect_v5.py audit --out DIR   -> DIR/parse_audit.json
  judge-inputs        python collect_v5.py judge-inputs --out DIR -> DIR/judge_inputs.jsonl
                      (bran-judge-input/1 for tools/judge)
"""

import argparse
import base64
import hashlib
import itertools
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "tools" / "corpus"))
sys.path.insert(0, str(REPO / "tools" / "evidence"))

OLLAMA = "http://localhost:11434"
MODELS = ["llama3.2:3b", "mistral", "gemma2:2b", "phi3:mini", "qwen2.5:3b"]   # v3/v4 list order
EMBED_MODEL = "nomic-embed-text"
V3_MANIFEST = HERE.parent / "v3" / "results" / "run_manifest.json"
OLLAMA_LOG = Path(os.environ.get("BRAN_OLLAMA_LOG", "ollama.log"))
TEMPERATURE, SEED = 0.7, 42
NUM_CTX = 4096                     # explicit: the answer prompt (~1.8k tokens) + 512 must fit
QUERY_NUM_PREDICT, ANSWER_NUM_PREDICT = 32, 512
QUERY_MAX_WORDS = 12
K = 5
MAX_CITATIONS = 3
DISPATCH_SEED = 20261101
TIMEOUT_S = 900
MAX_ATTEMPTS = 3
SPLIT_FILES = {"dev": "benchmark/items_dev.jsonl", "conf": "benchmark/items_confirmatory.jsonl"}
PROMPT_FILES = ["prompts/system_v5.txt", "prompts/query_v5.txt", "prompts/answer_v5.txt",
                "prompts/fragments_v5.json"]
SCHEMA_FILES = ["schema/query_v5.schema.json", "schema/answer_v5.schema.json"]
DENSE_DIR = REPO / "corpus-cache" / "scifact_dense"
DENSE_FORMAT = "bran-dense-index/1"
DENSE_DOC_PREFIX, DENSE_QUERY_PREFIX = "search_document: ", "search_query: "
FREEZE = HERE / "FREEZE.json"
CONF_FROZEN = (["real-agent-eval/v5/collect_v5.py", "real-agent-eval/v5/benchmark/items_confirmatory.jsonl",
                "tools/corpus/corpus_manifest.json", "tools/corpus/retrieve.py", "tools/corpus/build.py",
                "corpus-cache/scifact_dense/dense_manifest.json"]
               + [f"real-agent-eval/v5/{p}" for p in PROMPT_FILES + SCHEMA_FILES])

# Fields an agent may see (README "Gold-bearing fields ... must never show"). Whitelist only.
VIEW_FIELDS = ("id", "order", "split", "item_type", "answer_format", "answer_schema", "corpus", "question")

_seq_lock = threading.Lock()
_seq = {"answer": 0, "query": 0}


def next_seq(kind):
    with _seq_lock:
        s = _seq[kind]
        _seq[kind] += 1
        return s


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_text(s):
    return sha256_bytes(s.encode("utf-8"))


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 22), b""):
            h.update(blk)
    return h.hexdigest()


def atomic_dump(obj, path):
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def http_json(path, payload=None, timeout=30):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{OLLAMA}{path}", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ── item view, prompts, schemas ─────────────────────────────────

def agent_view(item):
    v = {k: item[k] for k in VIEW_FIELDS}
    if item.get("options"):
        v["options"] = [{"letter": o["letter"], "text": o["text"]} for o in item["options"]]
    return v


_DELIM = re.compile(r"[<>＜＞‹›«»〈〉〈〉❬-❱⟨⟩﹤﹥]{3,}")   # = tools/evidence/support/check.py


def neutralize(s):
    s = unicodedata.normalize("NFC", s)
    s = "".join(ch for ch in s if ch in "\n\t" or unicodedata.category(ch) != "Cc")
    return _DELIM.sub("[x]", s)


def fill(template, slots):
    out = template
    for k, v in slots.items():
        out = out.replace("{{" + k + "}}", v)
    assert "{{" not in out, out
    return out


class Prompts:
    def __init__(self):
        self.system = (HERE / "prompts/system_v5.txt").read_text()
        self.query = (HERE / "prompts/query_v5.txt").read_text()
        self.answer = (HERE / "prompts/answer_v5.txt").read_text()
        self.frag = json.loads((HERE / "prompts/fragments_v5.json").read_text())
        self.query_schema = json.loads((HERE / "schema/query_v5.schema.json").read_text())
        self.answer_schema_tpl = json.loads((HERE / "schema/answer_v5.schema.json").read_text())
        self.hashes = {p: sha256_file(HERE / p) for p in PROMPT_FILES + SCHEMA_FILES}

    def query_prompt(self, v):
        f = self.frag
        return fill(self.query, {"TARGET": f["target"][v["answer_format"]],
                                 "TASK_LABEL": f["task_label"][v["answer_format"]],
                                 "QUESTION": v["question"]})          # options deliberately absent

    def task_block(self, v):
        lab = self.frag["task_label"][v["answer_format"]]
        s = f"{lab}: {v['question']}"
        if v.get("options"):
            s += "\n\nOptions:\n" + "\n".join(f"{o['letter']}. {o['text']}" for o in v["options"])
        return s

    def answer_prompt(self, v, query, passages, mode):
        f = self.frag
        if mode == "closed_book":
            ev, cit = f["no_evidence"], f["citation_instruction"]["closed_book"]
        elif not passages:
            ev, cit = f["no_evidence"], f["citation_instruction"]["no_passages"]
        else:
            body = "\n\n".join(f"[{p['label']}] {neutralize(p['title'])}\n{neutralize(p['text'])}" for p in passages)
            ev = (fill(f["evidence_header"], {"QUERY": neutralize(query)}) + "\n"
                  + f["evidence_open"] + "\n" + body + "\n" + f["evidence_close"])
            cit = f["citation_instruction"]["retrieved"]
        return fill(self.answer, {"TASK_BLOCK": self.task_block(v), "EVIDENCE_BLOCK": ev,
                                  "FORMAT_INSTRUCTION": f["format_instruction"][v["answer_format"]],
                                  "CITATION_INSTRUCTION": cit})

    def answer_schema(self, v, labels):
        s = json.loads(json.dumps(self.answer_schema_tpl))
        a = dict(v["answer_schema"])
        if a.get("type") == "string":
            a.setdefault("minLength", 1)      # an empty entity string is not an answer
        s["properties"]["answer"] = a
        if labels:
            s["properties"]["citations"]["items"]["enum"] = list(labels)
            s["properties"]["citations"]["maxItems"] = min(MAX_CITATIONS, len(labels))
        else:
            s["properties"]["citations"] = {"type": "array", "maxItems": 0}
        return s


def canon_json_text(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ── conflict-keeping assignments (§3.2) ─────────────────────────

def retriever_assignment(v):
    """SciFact: seeded per-item split of the 5 models into BM25 and dense (2 or 3 dense,
    each model dense with probability 1/2). Other corpora: BM25 for all."""
    if v["corpus"] != "scifact":
        return {m: "bm25" for m in MODELS}
    r = random.Random("v5-ret:" + v["id"])
    perm = list(MODELS)
    r.shuffle(perm)
    n_dense = 3 if r.random() < 0.5 else 2
    return {m: ("dense" if m in perm[:n_dense] else "bm25") for m in MODELS}


def closed_book_set(v):
    pairs = list(itertools.combinations(MODELS, 2))      # each model in 4 of 10 pairs = 40%
    return list(random.Random("v5-cb:" + v["id"]).choice(pairs))


# ── retrieval ───────────────────────────────────────────────────

class Retrieval:
    def __init__(self, corpora, need_dense, verify_index):
        import retrieve as R
        import build as B
        self.R, self.B = R, B
        self.manifest = B.load_manifest()
        self.corpora, self.locks = {}, {}
        for cid in sorted(corpora):
            c = R.load(cid, verify=verify_index)
            if c.index_sha256 != self.manifest["corpora"][cid]["index"]["index_sha256"]:
                sys.exit(f"ABORT: {cid} index_sha256 differs from corpus_manifest.json")
            self.corpora[cid] = c
            self.locks[cid] = threading.Lock()
        self.dense = DenseIndex.load(self.manifest) if need_dense else None
        self.dense_lock = threading.Lock()

    def info(self):
        out = {"corpus_manifest_sha256": sha256_file(self.B.MANIFEST_PATH),
               "retrieve_py_sha256": sha256_file(Path(self.R.__file__)),
               "build_py_sha256": sha256_file(Path(self.B.__file__)),
               "corpora": {cid: {"index_sha256": c.index_sha256, "index_dir": str(c.index_dir),
                                 "corpus_sha256": self.manifest["corpora"][cid].get("corpus_sha256")}
                           for cid, c in self.corpora.items()}}
        if self.dense:
            out["dense"] = self.dense.info()
        return out

    def passage_view(self, rank, key):
        p = self.R.get_passage(key)
        return {"label": f"P{rank + 1}", "passage_key": key, "title": p["title"], "text": p["text"],
                "content_sha256": sha256_text(p["content"]), "chars": len(p["content"])}

    def run(self, retriever, query, corpus_id):
        t0 = time.monotonic()
        if retriever == "bm25":
            with self.locks[corpus_id]:
                rec = self.R.retrieve(query, self.corpora[corpus_id], k=K)
            extra = {}
        else:
            with self.dense_lock:
                rec, extra = self.dense.retrieve(query, K, self.R.seal)
        passages = [self.passage_view(i, r["passage_key"]) for i, r in enumerate(rec["results"])]
        return {"retriever": retriever, "record": rec, "record_verified": self.R.verify_record(rec),
                "retrieval_sha256": rec["retrieval_sha256"], **extra,
                "passages": [{k: p[k] for k in ("label", "passage_key", "content_sha256", "chars")} for p in passages],
                "elapsed_s": round(time.monotonic() - t0, 4)}, passages


class DenseIndex:
    """SciFact dense retrieval (design §3.2): nomic-embed-text over every scifact passage's
    content (title + "\\n" + text), L2-normalised float32, cosine via dot product;
    score_q = round_half_even(1000 * float64(cos)); order (-score_q, key bytes); top k.
    Records reuse the bran-retrieval/1 fields; `index_sha256` names the dense index."""

    def __init__(self, keys, emb, man):
        self.keys, self.emb, self.man = keys, emb, man
        self.index_sha256 = man["index_sha256"]

    @classmethod
    def load(cls, corpus_manifest):
        import numpy as np
        mf = DENSE_DIR / "dense_manifest.json"
        if not mf.exists():
            sys.exit(f"ABORT: {mf} missing; run `collect_v5.py build-dense` first")
        man = json.loads(mf.read_text())
        if man["scifact_corpus_sha256"] != corpus_manifest["corpora"]["scifact"]["corpus_sha256"]:
            sys.exit("ABORT: dense index was built on a different scifact corpus")
        if sha256_file(DENSE_DIR / "embeddings.f32.npy") != man["embeddings_sha256"]:
            sys.exit("ABORT: dense embeddings hash mismatch")
        keys = (DENSE_DIR / "keys.txt").read_text().split("\n")[:-1]
        if sha256_text("\n".join(keys) + "\n") != man["keys_sha256"]:
            sys.exit("ABORT: dense keys hash mismatch")
        return cls(keys, np.load(DENSE_DIR / "embeddings.f32.npy"), man)

    def info(self):
        return {"dense_manifest_sha256": sha256_file(DENSE_DIR / "dense_manifest.json"), **self.man}

    def retrieve(self, query, k, seal):
        import numpy as np
        vec = embed([DENSE_QUERY_PREFIX + query])[0]
        q = np.asarray(vec, dtype=np.float32)
        q = q / np.float32(np.linalg.norm(q))
        sc = np.rint((self.emb @ q).astype(np.float64) * 1000.0).astype(np.int64)
        # full sort over every passage (10k): ties at the k-th score_q are settled by key
        cand = sorted((-int(s), key.encode("utf-8")) for s, key in zip(sc.tolist(), self.keys) if s > 0)
        res = [{"passage_key": key.decode("utf-8"), "score_q": -neg} for neg, key in cand[:k]]
        rec = seal({"schema": "bran-retrieval/1", "query": query, "corpus_id": "scifact",
                    "index_sha256": self.index_sha256, "k": k, "results": res})
        qb = q.tobytes()
        return rec, {"query_embedding_sha256": sha256_bytes(qb),
                     "query_embedding_f32_b64": base64.b64encode(qb).decode("ascii")}


def embed(texts):
    d = http_json("/api/embed", {"model": EMBED_MODEL, "input": texts, "truncate": True,
                                 "options": {"seed": SEED}}, timeout=600)
    return d["embeddings"]


def cmd_build_dense(args):
    import numpy as np
    import build as B
    man = B.load_manifest()
    sc = man["corpora"]["scifact"]
    DENSE_DIR.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(l) for l in open(REPO / sc["passages"]["file"], "rb")]
    keys = [r["key"] for r in rows]
    vecs, t0 = [], time.time()
    for i in range(0, len(rows), args.batch):
        batch = [DENSE_DOC_PREFIX + B.passage_content(r["title"], r["text"]) for r in rows[i:i + args.batch]]
        vecs.extend(embed(batch))
        if (i // args.batch) % 20 == 0:
            print(f"  embedded {i + len(batch)}/{len(rows)} {time.time() - t0:.0f}s", flush=True)
    emb = np.asarray(vecs, dtype=np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True).astype(np.float32)
    np.save(DENSE_DIR / "embeddings.f32.npy", emb)
    (DENSE_DIR / "keys.txt").write_text("\n".join(keys) + "\n")
    tags = {m["name"]: m for m in http_json("/api/tags")["models"]}
    digest = (tags.get(EMBED_MODEL) or tags.get(EMBED_MODEL + ":latest"))["digest"]
    body = {"format": DENSE_FORMAT, "model": EMBED_MODEL, "model_digest": digest,
            "ollama_version": http_json("/api/version")["version"],
            "doc_prefix": DENSE_DOC_PREFIX, "query_prefix": DENSE_QUERY_PREFIX,
            "content": "build.passage_content(title, text)", "normalise": "L2, float32",
            "score_q": "round_half_even(1000*float64(dot(emb, q)))", "order": "(-score_q, passage_key utf-8)",
            "scifact_corpus_sha256": sc["corpus_sha256"], "n": len(keys), "dim": int(emb.shape[1]),
            "embeddings_sha256": sha256_file(DENSE_DIR / "embeddings.f32.npy"),
            "keys_sha256": sha256_text("\n".join(keys) + "\n")}
    man_out = {**body, "index_sha256": sha256_text(canon_json_text(body)), "build_s": round(time.time() - t0, 1)}
    atomic_dump(man_out, DENSE_DIR / "dense_manifest.json")
    print(json.dumps(man_out, indent=1))


# ── start-up checks ─────────────────────────────────────────────

def verify_freeze(split):
    if not FREEZE.exists():
        if split == "conf":
            sys.exit("ABORT: --split conf requires real-agent-eval/v5/FREEZE.json (prereg freeze, lane L0)")
        return {"FREEZE.json": None, "note": "no FREEZE.json; dev runs before the freeze"}
    freeze = json.loads(FREEZE.read_text())
    listed = freeze.get("sha256", {})
    bad = {p: (h, sha256_file(REPO / p) if (REPO / p).exists() else None)
           for p, h in listed.items() if not (REPO / p).exists() or sha256_file(REPO / p) != h}
    if bad:
        sys.exit(f"ABORT: FREEZE.json hash mismatch: {bad}")
    if split == "conf":
        missing = [p for p in CONF_FROZEN if p not in listed]
        if missing:
            sys.exit(f"ABORT: confirmatory collection requires these files frozen in FREEZE.json: {missing}")
    return {"FREEZE.json_sha256": sha256_file(FREEZE), "verified": sorted(listed)}


def verify_digests(need_embed):
    v3 = json.loads(V3_MANIFEST.read_text())["model_digests"]
    tags = {m["name"]: m for m in http_json("/api/tags", timeout=10)["models"]}
    out, bad = {}, []
    for m in MODELS + ([EMBED_MODEL] if need_embed else []):
        t = tags.get(m) or tags.get(f"{m}:latest")
        if t is None:
            bad.append((m, "missing"))
            continue
        show = http_json("/api/show", {"model": m})
        out[m] = {"name": t["name"], "digest": t["digest"],
                  "quantization": t["details"].get("quantization_level"),
                  "parameter_size": t["details"].get("parameter_size"),
                  "api_show_details": show.get("details"),
                  "api_show_modelfile_sha256": sha256_text(show.get("modelfile", "")),
                  "v3_digest": v3.get(m, {}).get("digest")}
        if m in MODELS and t["digest"] != v3[m]["digest"]:
            bad.append((m, t["digest"], v3[m]["digest"]))
    if bad:
        sys.exit(f"ABORT: model digest mismatch vs v3 run manifest: {bad}")
    return out


def server_env():
    try:
        lines = [ln for ln in OLLAMA_LOG.read_text(errors="replace").splitlines() if 'msg="server config"' in ln]
        last = lines[-1] if lines else ""
        env = {}
        for k in ("OLLAMA_NUM_PARALLEL", "OLLAMA_MAX_LOADED_MODELS", "OLLAMA_KEEP_ALIVE", "OLLAMA_CONTEXT_LENGTH",
                  "OLLAMA_FLASH_ATTENTION", "OLLAMA_KV_CACHE_TYPE", "OLLAMA_MAX_QUEUE", "OLLAMA_NEW_ENGINE"):
            mm = re.search(rf"{k}:(\S*)", last)
            env[k] = mm.group(1) if mm else None
        return {"log": str(OLLAMA_LOG), "server_config_line": last, "parsed": env}
    except Exception as e:
        return {"error": repr(e)}


# ── requests ────────────────────────────────────────────────────

def options(num_predict):
    return {"temperature": TEMPERATURE, "seed": SEED, "num_predict": num_predict, "num_ctx": NUM_CTX}


def _attempt(model, system, prompt, fmt, num_predict, timeout):
    payload = {"model": model, "prompt": prompt, "system": system, "stream": False,
               "format": fmt, "options": options(num_predict)}
    req = urllib.request.Request(f"{OLLAMA}/api/generate", data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    a = {"start_wall": time.time(), "start_mono": time.monotonic()}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        a["end_mono"], a["end_wall"] = time.monotonic(), time.time()
        a["data"] = data
        a["error"] = None if data.get("response") is not None else "no response field"
    except Exception as e:
        a["end_mono"], a["end_wall"] = time.monotonic(), time.time()
        a["data"], a["error"] = None, repr(e)
    return a


def generate(model, system, prompt, fmt, num_predict, timeout, seq_kind):
    rec = {"model": model, "request_seed": SEED, "options": options(num_predict),
           "prompt": prompt, "prompt_sha256": sha256_text(prompt),
           "format_sha256": sha256_text(canon_json_text(fmt)), "attempts": []}
    for k in range(MAX_ATTEMPTS):
        a = _attempt(model, system, prompt, fmt, num_predict, timeout)
        rec["attempts"].append({x: a[x] for x in ("start_wall", "end_wall", "error")})
        if a["error"] is None:
            rec["arrival_seq"] = next_seq(seq_kind)
            data = a["data"]
            rec.update(start_wall=a["start_wall"], start_mono=a["start_mono"],
                       end_wall=a["end_wall"], end_mono=a["end_mono"],
                       raw_response=data.get("response", ""), error=None, n_attempts=k + 1,
                       ollama_meta={x: data.get(x) for x in
                                    ["total_duration", "load_duration", "prompt_eval_count",
                                     "prompt_eval_duration", "eval_count", "eval_duration",
                                     "done_reason", "created_at"]})
            rec["elapsed_s"] = round(rec["end_mono"] - rec["start_mono"], 3)
            return rec
    rec["arrival_seq"] = next_seq(seq_kind)
    rec.update(start_wall=rec["attempts"][0]["start_wall"], start_mono=None,
               end_wall=rec["attempts"][-1]["end_wall"], end_mono=None, raw_response="",
               ollama_meta=None, error=rec["attempts"][-1]["error"], n_attempts=MAX_ATTEMPTS, elapsed_s=None)
    return rec


def ps_snapshot():
    try:
        return [m["name"] for m in http_json("/api/ps", timeout=5).get("models", [])]
    except Exception as e:
        return [f"error:{e!r}"]


# ── parsing ─────────────────────────────────────────────────────

_Q_PARTIAL = re.compile(r'"query"\s*:\s*"((?:[^"\\]|\\.)*)')


def parse_query(q, v):
    """-> (query_used, source). Never fails: falls back to the question text (gold-blind)."""
    raw = q.get("raw_response") or ""
    text, src = None, None
    if q.get("error") is None:
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict) and isinstance(obj.get("query"), str):
                text, src = obj["query"], "json"
        except Exception:
            m = _Q_PARTIAL.search(raw)
            if m:
                try:
                    text = json.loads('"' + m.group(1) + '"')
                except Exception:
                    text = m.group(1)
                src = "json_partial"
    words = (text or "").split()
    if not words:
        return " ".join(v["question"].split()), "fallback_question"
    return " ".join(words[:QUERY_MAX_WORDS]), src + ("_cut12" if len(words) > QUERY_MAX_WORDS else "")


def parse_answer(rec, v, labels, label_keys):
    out = {"status": None, "answer": None, "citations": [], "citation_keys": [], "invalid_citations": [],
           "confidence": None, "reasoning_chars": None, "violations": []}
    if rec.get("error") is not None:
        out["status"] = "request_error"
        return out
    truncated = (rec.get("ollama_meta") or {}).get("done_reason") == "length"
    try:
        obj = json.loads(rec["raw_response"])
    except Exception:
        out["status"] = "truncated" if truncated else "json_error"
        return out
    if not isinstance(obj, dict):
        out["status"] = "json_error"
        return out
    viol = []
    ans = obj.get("answer")
    a_sch = v["answer_schema"]
    if "enum" in a_sch:
        if ans not in a_sch["enum"]:
            viol.append("answer_not_in_enum")
    elif not isinstance(ans, str) or not ans.strip() or len(ans) > a_sch.get("maxLength", 60):
        viol.append("answer_bad_string")
    cits = obj.get("citations")
    if not isinstance(cits, list):
        viol.append("citations_not_list")
        cits = []
    if len(cits) > MAX_CITATIONS:
        viol.append("too_many_citations")
    conf = obj.get("confidence")
    if conf not in ("high", "medium", "low"):
        viol.append("confidence_bad")
    reasoning = obj.get("reasoning")
    if not isinstance(reasoning, str):
        viol.append("reasoning_missing")
    elif len(reasoning) > 600:
        viol.append("reasoning_too_long")
    valid = [c for c in cits if c in labels]
    out.update(answer=ans if "answer_not_in_enum" not in viol and "answer_bad_string" not in viol else None,
               citations=list(dict.fromkeys(valid)),
               citation_keys=[label_keys[c] for c in dict.fromkeys(valid)],
               invalid_citations=[c for c in cits if c not in labels], confidence=conf,
               reasoning_chars=len(reasoning) if isinstance(reasoning, str) else None,
               violations=viol)
    if out["invalid_citations"]:
        viol.append("citation_not_shown")
    # an answer is parsed iff the answer field is valid; other violations are audited, not fatal
    out["status"] = "ok" if out["answer"] is not None and not viol else ("ok_with_violations" if out["answer"] is not None else "schema_violation")
    return out


# ── one item ────────────────────────────────────────────────────

def run_agent(model, v, P, retr, mode, retriever, timeout):
    r = {"model": model, "mode": mode}
    passages, query = [], None
    if mode == "grounded":
        q = generate(model, P.system, P.query_prompt(v), P.query_schema, QUERY_NUM_PREDICT, timeout, "query")
        query, qsrc = parse_query(q, v)
        q["query_used"], q["query_source"] = query, qsrc
        q["query_arrival_seq"] = q.pop("arrival_seq")
        r["query_turn"] = q
        try:
            r["retrieval"], passages = retr.run(retriever, query, v["corpus"])
        except Exception as e:      # recorded; the agent then answers with no passages
            r["retrieval"] = {"retriever": retriever, "error": repr(e), "passages": []}
            passages = []
    else:
        r["query_turn"], r["retrieval"] = None, None
    labels = [p["label"] for p in passages]
    schema = P.answer_schema(v, labels)
    a = generate(model, P.system, P.answer_prompt(v, query, passages, mode), schema,
                 ANSWER_NUM_PREDICT, timeout, "answer")
    a["schema"] = schema
    r["answer_turn"] = a
    r["arrival_seq"] = a["arrival_seq"]
    r["parsed"] = parse_answer(a, v, labels, {p["label"]: p["passage_key"] for p in passages})
    return r


def run_item(item, P, retr, order, timeout, mixed_fleet):
    v = agent_view(item)
    assign = retriever_assignment(v)
    cb = closed_book_set(v) if mixed_fleet else []
    out = [None] * len(order)
    stop = threading.Event()
    ps_samples = []

    def sampler():
        while not stop.is_set():
            ps_samples.append((round(time.time(), 3), ps_snapshot()))
            stop.wait(2.0)

    def worker(i, m):
        try:
            out[i] = run_agent(m, v, P, retr, "closed_book" if m in cb else "grounded", assign[m], timeout)
        except Exception as e:      # never silently dropped
            out[i] = {"model": m, "harness_error": repr(e), "arrival_seq": next_seq("answer"),
                      "parsed": {"status": "harness_error"}}

    t0w, t0 = time.time(), time.monotonic()
    st = threading.Thread(target=sampler, daemon=True)
    st.start()
    threads = []
    for i, m in enumerate(order):
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
        r["retriever"] = None if r.get("mode") == "closed_book" else assign[r["model"]]
    return {"schema": "bran-v5-raw/1", "id": v["id"], "order": v["order"], "split": v["split"],
            "answer_format": v["answer_format"], "corpus": v["corpus"],
            "item_view": v, "item_view_sha256": sha256_text(canon_json_text(v)),
            "arm": "mixed_fleet" if mixed_fleet else "grounded", "closed_book_models": cb,
            "retriever_assignment": assign,
            "dispatch_order": order, "arrival_order": [r["model"] for r in recs],
            "list_order": MODELS, "responses": recs,
            "retrieval_record_ids": {r["model"]: (r.get("retrieval") or {}).get("retrieval_sha256") for r in recs},
            "item_start_wall": t0w, "item_wall_s": round(time.monotonic() - t0, 3),
            "ollama_ps_samples": ps_samples}


# ── collect ─────────────────────────────────────────────────────

def cmd_collect(args):
    out_dir = Path(args.out).resolve() if args.out else HERE / "results" / args.split
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    freeze = verify_freeze(args.split)
    P = Prompts()
    item_file = HERE / SPLIT_FILES[args.split]
    items = sorted((json.loads(l) for l in open(item_file)), key=lambda x: x["order"])
    assert [x["order"] for x in items] == list(range(len(items)))
    rng = random.Random(DISPATCH_SEED)
    orders = {}
    for x in items:
        o = list(MODELS)
        rng.shuffle(o)
        orders[x["id"]] = o
    if args.n_items is not None:
        items = items[:args.n_items]
    if args.ids:
        want = set(args.ids)
        unknown = want - {x["id"] for x in items}
        if unknown:
            sys.exit(f"ABORT: unknown ids for split {args.split}: {sorted(unknown)}")
        items = [x for x in items if x["id"] in want]

    corpora = {x["corpus"] for x in items}
    need_dense = "scifact" in corpora and any(
        a == "dense" for x in items for a in retriever_assignment(agent_view(x)).values())
    digests = verify_digests(need_dense)
    version = http_json("/api/version", timeout=5)
    t_load = time.time()
    retr = Retrieval(corpora, need_dense, verify_index=(args.split == "conf" or args.verify_index))
    load_s = round(time.time() - t_load, 1)

    mf = out_dir / "run_manifest.json"
    manifest = json.loads(mf.read_text()) if mf.exists() else {"sessions": []}
    session = {
        "started_wall": time.time(), "ollama_version": version,
        "ollama_list": subprocess.run(["ollama", "list"], capture_output=True, text=True).stdout,
        "model_digests": digests, "list_order": MODELS,
        "system_prompt": P.system, "system_prompt_sha256": sha256_text(P.system),
        "prompt_and_schema_sha256": P.hashes,
        "options": {"query_turn": options(QUERY_NUM_PREDICT), "answer_turn": options(ANSWER_NUM_PREDICT)},
        "k": K, "query_max_words": QUERY_MAX_WORDS, "max_citations": MAX_CITATIONS,
        "dispatch_seed": DISPATCH_SEED, "timeout_s": args.timeout, "max_attempts": MAX_ATTEMPTS,
        "arm": "mixed_fleet" if args.mixed_fleet else "grounded",
        "split": args.split, "item_file": SPLIT_FILES[args.split], "item_file_sha256": sha256_file(item_file),
        "items_requested": [x["id"] for x in items] if (args.ids or args.n_items) else "all",
        "freeze": freeze, "collect_v5_py_sha256": sha256_file(__file__),
        "retrieval": retr.info(), "retrieval_load_s": load_s,
        "server_env": server_env(), "python": sys.version, "argv": sys.argv,
        "dispatch": "all 5 agents per item submitted concurrently (one thread each) in an order shuffled by "
                    "random.Random(dispatch_seed); each thread runs query turn -> retrieval -> answer turn; "
                    "items run sequentially in frozen order",
        "sequencer": "process-wide lock+counters: arrival_seq at the answer turn's successful body read; "
                     "query_arrival_seq (separate counter) at the query turn's",
    }
    manifest["sessions"].append(session)
    atomic_dump(manifest, mf)

    t0 = time.time()
    done = skipped = 0
    for i, it in enumerate(items):
        order = orders[it["id"]]
        f = raw_dir / f"{it['id']}.json"
        if f.exists():
            prev = json.loads(f.read_text())
            if prev["dispatch_order"] != order:
                sys.exit(f"ABORT: resume dispatch-order mismatch on {it['id']}")
            _seq["answer"] = max(_seq["answer"], max(r["arrival_seq"] for r in prev["responses"]) + 1)
            qs = [r["query_turn"]["query_arrival_seq"] for r in prev["responses"] if r.get("query_turn")]
            if qs:
                _seq["query"] = max(_seq["query"], max(qs) + 1)
            skipped += 1
            continue
        raw = run_item(it, P, retr, order, args.timeout, args.mixed_fleet)
        atomic_dump(raw, f)
        done += 1
        st = [r["parsed"]["status"] for r in raw["responses"]]
        print(f"[{i+1}/{len(items)}] {it['id']} {raw['item_wall_s']:.1f}s "
              f"arrival={[m.split(':')[0] for m in raw['arrival_order']]} "
              f"ok={sum(s == 'ok' for s in st)}/5 answers={[r['parsed'].get('answer') for r in raw['responses']]} "
              f"elapsed={time.time()-t0:.0f}s", flush=True)
    session["finished_wall"] = time.time()
    session["n_collected"], session["n_skipped_existing"] = done, skipped
    session["n_raw_files"] = len(list(raw_dir.glob("*.json")))
    atomic_dump(manifest, mf)
    print(f"done: collected={done} skipped={skipped} raw_files={session['n_raw_files']}", flush=True)


# ── audit (reads raw records only; never gold) ──────────────────

def norm_answer(a, fmt):
    if a is None:
        return None
    if fmt != "entity":
        return a
    s = unicodedata.normalize("NFKC", a).lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"^(the|a|an)\s+", "", s.strip())
    return " ".join(s.split())


def cmd_audit(args):
    out_dir = Path(args.out).resolve()
    raws = [json.loads(p.read_text()) for p in sorted((out_dir / "raw").glob("*.json"))]
    per = {m: {"n": 0, "status": {}, "violations": {}, "answer_truncated": 0, "answer_eval_count": [],
               "answer_prompt_tokens": [], "query_source": {}, "query_truncated": 0, "query_words": [],
               "n_citing": 0, "citations": 0, "citations_valid": 0, "citations_invalid": 0,
               "retrieval_empty": 0, "retrieval_unverified": 0, "query_s": [], "answer_s": []} for m in MODELS}
    items = []
    for raw in raws:
        answers = []
        for r in raw["responses"]:
            a = per[r["model"]]
            a["n"] += 1
            p = r["parsed"]
            a["status"][p["status"]] = a["status"].get(p["status"], 0) + 1
            for x in p.get("violations", []):
                a["violations"][x] = a["violations"].get(x, 0) + 1
            at = r.get("answer_turn") or {}
            meta = at.get("ollama_meta") or {}
            if meta.get("done_reason") == "length":
                a["answer_truncated"] += 1
            if meta.get("eval_count") is not None:
                a["answer_eval_count"].append(meta["eval_count"])
                a["answer_prompt_tokens"].append(meta["prompt_eval_count"])
            if at.get("elapsed_s") is not None:
                a["answer_s"].append(at["elapsed_s"])
            q = r.get("query_turn")
            if q:
                a["query_source"][q["query_source"]] = a["query_source"].get(q["query_source"], 0) + 1
                if (q.get("ollama_meta") or {}).get("done_reason") == "length":
                    a["query_truncated"] += 1
                a["query_words"].append(len(q["query_used"].split()))
                if q.get("elapsed_s") is not None:
                    a["query_s"].append(q["elapsed_s"])
            ret = r.get("retrieval") or {}
            if r.get("mode") == "grounded" and not ret.get("passages"):
                a["retrieval_empty"] += 1
            if ret.get("record") and not ret.get("record_verified"):
                a["retrieval_unverified"] += 1
            nc = len(p.get("citations", [])) + len(p.get("invalid_citations", []))
            a["citations"] += nc
            a["citations_valid"] += len(p.get("citations", []))
            a["citations_invalid"] += len(p.get("invalid_citations", []))
            a["n_citing"] += nc > 0
            if p.get("answer") is not None:
                answers.append(norm_answer(p["answer"], raw["answer_format"]))
        # cited passages shared across agents (same passage_key)
        keysets = [set(r["parsed"].get("citation_keys", [])) for r in raw["responses"]]
        shown = [{x["passage_key"] for x in (r.get("retrieval") or {}).get("passages", [])} for r in raw["responses"]]
        items.append({"id": raw["id"], "corpus": raw["corpus"], "answer_format": raw["answer_format"],
                      "item_wall_s": raw["item_wall_s"], "n_parsed": len(answers),
                      "n_distinct_answers": len(set(answers)),
                      "answer_counts": sorted(([a, answers.count(a)] for a in set(answers)), key=lambda x: -x[1]),
                      "n_distinct_queries": len({r["query_turn"]["query_used"] for r in raw["responses"] if r.get("query_turn")}),
                      "n_distinct_passages_shown": len(set().union(*shown)) if shown else 0,
                      "n_cited_passage_keys_shared": sum(1 for k in set().union(*keysets) if sum(k in s for s in keysets) > 1)})

    def stats(xs):
        xs = sorted(xs)
        return None if not xs else {"n": len(xs), "mean": round(sum(xs) / len(xs), 2), "median": xs[len(xs) // 2],
                                    "min": xs[0], "max": xs[-1]}

    for m, a in per.items():
        for k in ("answer_eval_count", "answer_prompt_tokens", "query_words", "query_s", "answer_s"):
            a[k] = stats(a[k])
        a["parse_ok_rate"] = round(sum(v for s, v in a["status"].items() if s.startswith("ok")) / a["n"], 4) if a["n"] else None
        a["citation_validity_rate"] = round(a["citations_valid"] / a["citations"], 4) if a["citations"] else None
    tot_c = sum(a["citations"] for a in per.values())
    dist = {}
    for it in items:
        dist[it["n_distinct_answers"]] = dist.get(it["n_distinct_answers"], 0) + 1
    report = {"n_items": len(items), "per_model": per, "items": items,
              "item_wall_s": stats([it["item_wall_s"] for it in items]),
              "citation_validity_rate": round(sum(a["citations_valid"] for a in per.values()) / tot_c, 4) if tot_c else None,
              "n_distinct_answers_hist": dict(sorted(dist.items())),
              "items_with_disagreement": sum(it["n_distinct_answers"] > 1 for it in items),
              "note": "computed from raw records only; no gold field is read; no accuracy"}
    atomic_dump(report, out_dir / "parse_audit.json")
    print(json.dumps({k: report[k] for k in ("n_items", "item_wall_s", "citation_validity_rate",
                                             "n_distinct_answers_hist", "items_with_disagreement")}, indent=1))
    for m, a in per.items():
        print(m, json.dumps({k: a[k] for k in ("n", "status", "violations", "answer_truncated", "parse_ok_rate",
                                                "citation_validity_rate", "n_citing", "query_source",
                                                "query_truncated", "answer_eval_count", "query_s", "answer_s")}))


def cmd_judge_inputs(args):
    """Emit bran-judge-input/1 (tools/judge/judge.py) from raw records: one line per item.
    Shown passage text is the indexed content (title + "\n" + text, what the agent saw),
    re-read from the corpus and checked against the sealed content_sha256."""
    import retrieve as R
    out_dir = Path(args.out).resolve()
    lines, bad = [], 0
    for f in sorted((out_dir / "raw").glob("*.json")):
        raw = json.loads(f.read_text())
        agents = []
        for r in sorted(raw["responses"], key=lambda r: r["agent"]):
            shown = []
            for p in (r.get("retrieval") or {}).get("passages", []):
                c = R.get_passage(p["passage_key"])["content"]
                if sha256_text(c) != p["content_sha256"]:
                    sys.exit(f"ABORT: passage content changed: {p['passage_key']}")
                shown.append({"label": p["label"], "passage_key": p["passage_key"], "text": c})
            pa = r["parsed"]
            at = r.get("answer_turn") or {}
            reasoning = None
            if pa.get("answer") is not None:
                try:
                    reasoning = json.loads(at["raw_response"]).get("reasoning")
                except Exception:
                    pass
            agents.append({"agent_id": r["agent"], "model": r["model"],
                           "response_id": sha256_text((at.get("prompt_sha256") or "") + "\n" + (at.get("raw_response") or ""))[:16],
                           "parsed": pa.get("answer") is not None, "answer": pa.get("answer"),
                           "confidence": pa.get("confidence"), "reasoning": reasoning,
                           "citations": pa.get("citations", []) + pa.get("invalid_citations", []),
                           "shown": shown, "retrieval_sha256": (r.get("retrieval") or {}).get("retrieval_sha256")})
        lines.append({"format": "bran-judge-input/1", "item_id": raw["id"], "raw_sha256": sha256_file(f),
                      "agents": agents})
    with open(out_dir / "judge_inputs.jsonl", "w") as fh:
        for l in lines:
            fh.write(json.dumps(l, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"wrote {len(lines)} items to {out_dir / 'judge_inputs.jsonl'}")


def main():
    os.environ.setdefault("DISABLE_TQDM", "1")
    if len(sys.argv) > 1 and sys.argv[1] == "judge-inputs":
        sys.argv.pop(1)
        ap = argparse.ArgumentParser()
        ap.add_argument("--out", required=True)
        return cmd_judge_inputs(ap.parse_args())
    if len(sys.argv) > 1 and sys.argv[1] in ("build-dense", "audit"):
        cmd = sys.argv.pop(1)
        ap = argparse.ArgumentParser()
        if cmd == "build-dense":
            ap.add_argument("--batch", type=int, default=32)
            return cmd_build_dense(ap.parse_args())
        ap.add_argument("--out", required=True)
        return cmd_audit(ap.parse_args())
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "conf"], required=True)
    ap.add_argument("--n-items", type=int, help="first N items in frozen order (confirmatory: I)")
    ap.add_argument("--ids", nargs="*", help="subset by id (pilot/testing; use a scratch --out)")
    ap.add_argument("--out", help="output dir (default results/<split>/)")
    ap.add_argument("--timeout", type=int, default=TIMEOUT_S)
    ap.add_argument("--mixed-fleet", action="store_true", help="pre-declared fallback arm (§3.2)")
    ap.add_argument("--verify-index", action="store_true", help="hash index files on load (always on for conf)")
    cmd_collect(ap.parse_args())


if __name__ == "__main__":
    main()
