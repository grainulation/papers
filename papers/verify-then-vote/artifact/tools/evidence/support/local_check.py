#!/usr/bin/env python3
"""Local support checker: check.py's prompt, spans, neutralizer, sealing and record format,
with a local Ollama model (default mistral) as the backend -> bran-support/1.

This module reuses, unchanged, everything in check.py that decides what the model sees and
how its answer is sealed: bm25/1 span selection, neutralize(), the 0.2.0 prompt template
(prompt_template.txt, same sha256), RESPONSE_SCHEMA, check_text() (cache key =
(checker_id, rendered prompt)), build_record() and SupportCache. Only the backend differs:

  * POST /api/generate on localhost (no shell, no subprocess). The template's SYSTEM section
    goes in `system`, the rendered USER section in `prompt`; untrusted text never leaves the
    delimited USER section.
  * `format` = check.RESPONSE_SCHEMA (Ollama structured output: label enum + integer
    confidence 0..10000), greedy decoding (temperature 0), fixed seed, num_ctx 8192.
  * Strict parse of the raw response: exactly {label, confidence}, label in the enum,
    confidence an int 0..10000, done_reason "stop"; else parse_error. The response's model
    name must equal the pin, else model_mismatch. A prompt that may not fit the context
    (prompt_eval_count + num_predict > num_ctx; Ollama silently truncates) -> input_too_long.
  * The raw response string is the sealed model output (raw_output_sha256 hashes it verbatim).

Identity (checker_id, same formula as Rust Checker::compute_id):
  model         pin model name (mistral:latest)
  model_digest  the Ollama manifest digest; verified against /api/tags at construction
  decoding      temperature_x1000, top_k, top_p_x1000, num_ctx, num_predict, seed (all set)
  checker_tool_version
                <check SEMVER>-local<LOCAL_SEMVER>+<blob local_check.py>.<blob check.py>.
                <blob prompt_template.txt>.f<options/schema/endpoint hash>.ollama<server version>
                .srv<hash of the server config that changes numerics>
  So an Ollama upgrade, a different model digest, other options, or another flash-attention /
  KV-cache-type / parallelism setting all give a new checker_id.

Stdlib only. Run with `python3 -I`.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import check  # noqa: E402
from canonical import canonical_bytes, canonical_json, sha256_hex, git_blob_sha1  # noqa: E402

LOCAL_SEMVER = "0.1.0"
LOCAL_PIN_PATH = os.path.join(HERE, "local_pin.json")
# Prefer the public name; the fallback reads historical launch configurations.
OLLAMA_LOG = os.environ.get("OVERTURN_OLLAMA_LOG", os.environ.get("BRAN_OLLAMA_LOG", "ollama.log"))
# server settings that can change the numerics of a forward pass (hence greedy outputs)
SERVER_KEYS = ("OLLAMA_FLASH_ATTENTION", "OLLAMA_KV_CACHE_TYPE", "OLLAMA_NUM_PARALLEL", "OLLAMA_CONTEXT_LENGTH",
               "OLLAMA_NEW_ENGINE", "OLLAMA_LLM_LIBRARY")
META_KEYS = ("total_duration", "load_duration", "prompt_eval_count", "prompt_eval_duration", "eval_count",
             "eval_duration", "done_reason", "created_at", "model")


class OllamaError(RuntimeError):
    pass


def http_json(endpoint, path, body=None, timeout=30):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(endpoint.rstrip("/") + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def server_config(path=OLLAMA_LOG):
    """Parsed numerics-relevant settings from the last 'server config' line of the Ollama log.
    {} values are 'unknown' when the log cannot be read (still hashed, so it shows in the id)."""
    out = {k: "unknown" for k in SERVER_KEYS}
    try:
        with open(path, errors="replace") as fh:
            last = ""
            for ln in fh:
                if 'msg="server config"' in ln:
                    last = ln
    except OSError:
        return out
    for k in SERVER_KEYS:
        m = re.search(r"%s:(\S*?)(?=\s|\]|$)" % k, last)
        if m:
            out[k] = m.group(1)
    return out


def model_digest(endpoint, model):
    tags = {m["name"]: m for m in http_json(endpoint, "/api/tags", timeout=10)["models"]}
    t = tags.get(model) or tags.get(model + ":latest")
    if t is None:
        raise OllamaError("model %s is not installed" % model)
    return t["digest"], t.get("details") or {}


def decoding_block(options):
    """Rust Checker `decoding` fields (integers), all explicitly set."""
    return {"temperature_x1000": int(round(options["temperature"] * 1000)), "top_k": int(options["top_k"]),
            "top_p_x1000": int(round(options["top_p"] * 1000)), "num_ctx": int(options["num_ctx"]),
            "num_predict": int(options["num_predict"]), "seed": int(options["seed"])}


def _blob(path):
    with open(path, "rb") as fh:
        return git_blob_sha1(fh.read())[:12]


def load_local_pin(path=LOCAL_PIN_PATH):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def ollama_generate(endpoint, model, system, prompt, fmt, options, keep_alive, timeout):
    """One non-streaming /api/generate call. -> (data or None, error or None, wall_ms)."""
    body = {"model": model, "system": system, "prompt": prompt, "stream": False, "format": fmt,
            "options": dict(options), "keep_alive": keep_alive}
    t0 = time.monotonic()
    try:
        data = http_json(endpoint, "/api/generate", body, timeout=timeout)
        err = None if isinstance(data.get("response"), str) else "no response field"
    except urllib.error.HTTPError as e:
        data, err = None, "http %s: %s" % (e.code, e.read()[:300].decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001  (URLError, socket timeout, bad JSON)
        data, err = None, repr(e)
    return data, err, int((time.monotonic() - t0) * 1000)


def is_timeout(err):
    return err is not None and ("timed out" in err or "TimeoutError" in err)


def context_overflow(meta, options):
    pe = meta.get("prompt_eval_count")
    return isinstance(pe, int) and pe + int(options["num_predict"]) > int(options["num_ctx"])


def parse_check_response(data, pinned_model, options):
    """Strict parse of an Ollama /api/generate response for the support check. Never raises."""
    out = {"status": "parse_error", "label": None, "score_q": None, "model_output": None, "model_reported": None,
           "cost_usd": 0.0}
    meta = {k: data.get(k) for k in META_KEYS}
    out["meta"] = meta
    out["model_reported"] = data.get("model") if isinstance(data.get("model"), str) else None
    raw = data.get("response")
    out["model_output"] = raw if isinstance(raw, str) else None
    if out["model_reported"] != pinned_model:
        out["status"] = "model_mismatch"
        return out
    if context_overflow(meta, options):
        out["status"] = "input_too_long"
        return out
    if data.get("done_reason") != "stop" or not isinstance(raw, str):
        return out
    try:
        so = json.loads(raw)
    except ValueError:
        return out
    if not isinstance(so, dict) or set(so.keys()) != {"label", "confidence"}:
        return out
    lab, conf = so["label"], so["confidence"]
    if lab not in check.LABELS or isinstance(conf, bool) or not isinstance(conf, int) or not 0 <= conf <= 10000:
        return out
    out.update(status="ok", label=lab, score_q=conf)
    return out


class LocalChecker:
    """Duck-type compatible with check.Checker for check.check_text / build_record /
    run_checks_v5.run_checks / validate.run_items: .template, .checker_id, .checker_block(),
    .describe(), .call(user_prompt)."""

    def __init__(self, pin=None, template=None, verify=True, ollama_version=None, server=None, digest=None):
        self.pin = pin or load_local_pin()
        self.template = template or check.load_template()
        self.endpoint = self.pin["endpoint"]
        self.options = dict(self.pin["options"])
        if verify:
            got, self.model_details = model_digest(self.endpoint, self.pin["model"])
            if got != self.pin["model_digest"]:
                raise OllamaError("model digest %s != pin %s" % (got, self.pin["model_digest"]))
            self.ollama_version = ollama_version or http_json(self.endpoint, "/api/version", timeout=10)["version"]
        else:
            self.model_details = {}
            self.ollama_version = ollama_version or "unknown"
        # sealed as "sha256:<hex>" (the Ollama manifest digest; /api/tags reports the bare hex)
        self.model_digest = digest or ("sha256:" + self.pin["model_digest"])
        self.server = server if server is not None else server_config()
        self.flags = {"backend": self.pin["backend"], "endpoint_path": "/api/generate", "stream": False,
                      "options": decoding_block(self.options), "keep_alive": self.pin.get("keep_alive"),
                      "system": "@prompt_template.txt#SYSTEM", "format": check.RESPONSE_SCHEMA_JSON}
        self.flags_sha256 = sha256_hex(canonical_bytes(self.flags))
        self.server_sha256 = sha256_hex(canonical_bytes(self.server))
        self.tool_version = "%s-local%s+%s.%s.%s.f%s.ollama%s.srv%s" % (
            check.SEMVER, LOCAL_SEMVER, _blob(os.path.abspath(__file__)), _blob(os.path.join(HERE, "check.py")),
            _blob(check.TEMPLATE_PATH), self.flags_sha256[:12], self.ollama_version, self.server_sha256[:8])
        self.ident = {
            "model": self.pin["model"],
            "model_digest": self.model_digest,
            "prompt_template_sha256": self.template["sha256"],
            "decoding": decoding_block(self.options),
            "checker_tool_version": self.tool_version,
        }
        self.checker_id = check.compute_checker_id(self.ident)

    def checker_block(self, model_reported=None):
        b = dict(self.ident)
        b["checker_id"] = self.checker_id
        b["ollama_version"] = self.ollama_version
        return b

    def describe(self):
        return dict(self.checker_block(), backend=self.pin["backend"], endpoint=self.endpoint, flags=self.flags,
                    flags_sha256=self.flags_sha256, server_config=self.server, server_sha256=self.server_sha256,
                    model_details=self.model_details,
                    response_schema_sha256=sha256_hex(check.RESPONSE_SCHEMA_JSON.encode()))

    def call(self, user_prompt):
        data, err, wall = ollama_generate(self.endpoint, self.pin["model"], self.template["system"], user_prompt,
                                          check.RESPONSE_SCHEMA, self.options, self.pin.get("keep_alive"),
                                          int(self.pin.get("timeout_s", 600)))
        if err is not None:
            st = "timeout" if is_timeout(err) else "checker_error"
            return {"status": st, "error": err, "duration_ms": wall, "cost_usd": 0.0}
        res = parse_check_response(data, self.pin["model"], self.options)
        res["duration_ms"] = wall
        res["server_ms"] = (data.get("total_duration") or 0) // 1000000
        res["transcript"] = canonical_json(res.pop("meta"))
        return res


# ── command line ──

def cmd_id(args):
    print(json.dumps(LocalChecker().describe(), indent=1, sort_keys=True))
    return 0


def cmd_check(args):
    checker = LocalChecker()
    scache = check.SupportCache(args.support_cache or args.cache)
    n_ok = n_skip = 0
    with open(args.items, encoding="utf-8") as fh:
        items = [json.loads(l) for l in fh if l.strip()]
    for it in items:
        sid, r = check.check_contribution(checker, scache, args.cache, it, force=args.recheck)
        if sid is None:
            n_skip += 1
            print(json.dumps({"contribution_id": it.get("contribution_id"), "skipped": r}), file=sys.stderr)
            continue
        n_ok += 1
        print(canonical_json({"support_id": sid, "contribution_id": r["contribution_id"], "status": r["status"],
                              "label": r["label"], "score_q": r["score_q"]}))
    print("records=%d skipped=%d checker_id=%s" % (n_ok, n_skip, checker.checker_id), file=sys.stderr)
    return 0


def cmd_v5(args):
    """run_checks_v5 `check` with the local checker: checks_plan.jsonl -> checks_local.jsonl."""
    import run_checks_v5 as RC
    out = args.out or os.path.join(RC.V5, "results", args.split)
    if "v4/results/conf" in os.path.abspath(out).replace("\\", "/"):
        raise SystemExit("refused: v4 confirmatory data are blinded")
    cache_root = args.cache or os.path.join(out, "evidence-cache")
    support_root = args.support_cache or os.path.join(out, "evidence-cache-local")
    plan = RC.read_jsonl(os.path.join(out, "checks_plan.jsonl"))
    if args.limit:
        plan = plan[:args.limit]
    checker = LocalChecker()
    if args.expect_checker and checker.checker_id != args.expect_checker:
        raise SystemExit("ABORT: checker_id %s != expected %s" % (checker.checker_id, args.expect_checker))
    rows, _, wall = RC.run_checks(plan, checker, cache_root, support_root, args.workers, args.retries, None,
                                  os.path.join(out, "check_calls_local.jsonl"))
    RC.write_jsonl(os.path.join(out, args.out_name), rows)
    from collections import Counter
    st = Counter(r["status"] for r in rows)
    lab = Counter((r["label"] or "-") for r in rows if r["status"] == "ok")
    print(json.dumps({"checker_id": checker.checker_id, "planned": len(plan), "written": len(rows),
                      "status": dict(st), "labels": dict(lab), "wall_s": round(wall, 1)}, indent=1))
    return 0 if len(rows) == len(plan) else 2


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("checker-id").set_defaults(fn=cmd_id)
    c = sub.add_parser("check", help="like check.py check, with the local backend")
    c.add_argument("--items", required=True)
    c.add_argument("--cache", required=True)
    c.add_argument("--support-cache")
    c.add_argument("--recheck", action="store_true")
    c.set_defaults(fn=cmd_check)
    v = sub.add_parser("v5", help="v5 checks_plan.jsonl -> checks_local.jsonl (evaluate_v5 --checks format)")
    v.add_argument("--split", choices=["dev", "conf"], default="dev")
    v.add_argument("--out", help="split dir (default real-agent-eval/v5/results/<split>)")
    v.add_argument("--cache", help="evidence cache with captures/ and text/ (default <out>/evidence-cache)")
    v.add_argument("--support-cache", help="local support cache (default <out>/evidence-cache-local)")
    v.add_argument("--out-name", default="checks_local.jsonl")
    v.add_argument("--workers", type=int, default=1, help="OLLAMA_NUM_PARALLEL is 1: more workers only queue")
    v.add_argument("--retries", type=int, default=2)
    v.add_argument("--limit", type=int, default=0)
    v.add_argument("--expect-checker", default="")
    v.set_defaults(fn=cmd_v5)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
