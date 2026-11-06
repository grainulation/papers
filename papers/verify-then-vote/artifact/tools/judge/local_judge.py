#!/usr/bin/env python3
"""Local judge J_local and reader RS_local for eval v5 -> bran-judge/1, on a local Ollama model.

Same inputs, prompts and records as tools/judge/judge.py (J and RS, v3/SWARM3_DESIGN.md §5;
outside knowledge allowed, PREREG_DECISIONS.md item 6): the gold-blind item view, the
seeded candidate / passage order, prompt_J.txt / prompt_RS.txt unchanged (same sha256), the
per-call response schema (allowed-value enum or the RS answer schema, plus integer
confidence), the decision cache, sealed canonical records and the call log all come from
judge.py. Only the backend differs (v3/FRAMING.md §3.2):

  * POST /api/generate on localhost; the template's SYSTEM section in `system`, the rendered
    USER prompt in `prompt`, `format` = the call's response schema (Ollama structured output),
    greedy decoding (temperature 0), fixed seed, num_ctx 8192.
  * Strict parse: exactly {answer, confidence}; answer mapped through judge.make_validator
    (enum display value -> original value, or the RS free-answer rule); done_reason "stop";
    the response's model name must equal the pin (else model_mismatch). A prompt that may
    not fit the context (prompt_eval_count + num_predict > num_ctx: Ollama would silently
    truncate it) -> input_too_long, cached and sealed with no answer.
  * The raw response string is the sealed model output.

Identity: judge_id = judge.compute_judge_id over {model, model_digest ("sha256:<hex>",
verified against /api/tags), prompt_template_sha256, decoding (all six fields set),
judge_tool_version}; judge_tool_version binds this file, judge.py, the template, the
backend flags, judge.CONFIG, the Ollama server version and the numerics-relevant server
config (flash attention, KV cache type, parallelism).

Stdlib only. Run with `python3 -I`.
"""

import argparse
import csv
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
SUPPORT = os.path.join(TOOLS, "evidence", "support")
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, os.path.join(TOOLS, "evidence"))
sys.path.insert(0, SUPPORT)
sys.path.insert(0, HERE)
import judge as JG  # noqa: E402
import local_check as LC  # noqa: E402
from canonical import canonical_bytes, canonical_json, sha256_hex  # noqa: E402

LOCAL_SEMVER = "0.1.0"
LOCAL_PIN_PATH = os.path.join(HERE, "local_pin.json")
V5 = os.path.join(ROOT, "real-agent-eval", "v5")


def parse_judge_response(data, pinned_model, options, validate):
    out = {"status": "parse_error", "answer": None, "confidence": None, "model_output": None,
           "model_reported": None, "cost_usd": 0.0, "usage": None}
    meta = {k: data.get(k) for k in LC.META_KEYS}
    out["meta"] = meta
    out["usage"] = {k: meta[o] for k, o in (("input_tokens", "prompt_eval_count"), ("output_tokens", "eval_count"))
                    if isinstance(meta.get(o), int)}
    out["model_reported"] = data.get("model") if isinstance(data.get("model"), str) else None
    raw = data.get("response")
    out["model_output"] = raw if isinstance(raw, str) else None
    if out["model_reported"] != pinned_model:
        out["status"] = "model_mismatch"
        return out
    if LC.context_overflow(meta, options):
        out["status"] = "input_too_long"
        return out
    if data.get("done_reason") != "stop" or not isinstance(raw, str):
        return out
    try:
        so = json.loads(raw)
    except ValueError:
        return out
    if not isinstance(so, dict) or set(so.keys()) != {"answer", "confidence"}:
        return out
    ans, conf = so["answer"], so["confidence"]
    if not isinstance(ans, str) or isinstance(conf, bool) or not isinstance(conf, int) or not 0 <= conf <= 10000:
        return out
    val = validate(ans)
    if val is None:
        return out
    out.update(status="ok", answer=val, confidence=conf)
    return out


class LocalJudge:
    """Duck-type compatible with judge.Judge for judge.decide / run_batch / build_record."""

    def __init__(self, method, pin=None, template=None, verify=True, ollama_version=None, server=None, digest=None):
        if method not in JG.METHODS:
            raise ValueError("method must be J or RS")
        self.method = method
        self.pin = pin or load_local_pin()
        self.template = template or JG.load_template(method)
        self.endpoint = self.pin["endpoint"]
        self.options = dict(self.pin["options"])
        if verify:
            got, self.model_details = LC.model_digest(self.endpoint, self.pin["model"])
            if got != self.pin["model_digest"]:
                raise LC.OllamaError("model digest %s != pin %s" % (got, self.pin["model_digest"]))
            self.ollama_version = ollama_version or LC.http_json(self.endpoint, "/api/version", timeout=10)["version"]
        else:
            self.model_details = {}
            self.ollama_version = ollama_version or "unknown"
        self.server = server if server is not None else LC.server_config()
        self.flags = {"backend": self.pin["backend"], "endpoint_path": "/api/generate", "stream": False,
                      "options": LC.decoding_block(self.options), "keep_alive": self.pin.get("keep_alive"),
                      "system": "@template#SYSTEM", "format": JG.SCHEMA_PLACEHOLDER}
        self.flags_sha256 = sha256_hex(canonical_bytes(self.flags))
        self.config_sha256 = sha256_hex(canonical_bytes(JG.CONFIG))
        self.server_sha256 = sha256_hex(canonical_bytes(self.server))
        self.tool_version = "%s-local%s+%s.%s.%s.f%s.c%s.ollama%s.srv%s" % (
            JG.SEMVER, LOCAL_SEMVER, LC._blob(os.path.abspath(__file__)), LC._blob(os.path.join(HERE, "judge.py")),
            LC._blob(os.path.join(HERE, self.template["file"])), self.flags_sha256[:12], self.config_sha256[:12],
            self.ollama_version, self.server_sha256[:8])
        self.ident = {
            "model": self.pin["model"],
            "model_digest": digest or ("sha256:" + self.pin["model_digest"]),
            "prompt_template_sha256": self.template["sha256"],
            "decoding": LC.decoding_block(self.options),
            "judge_tool_version": self.tool_version,
        }
        self.judge_id = JG.compute_judge_id(self.ident)

    def block(self, runtime_ver):
        b = dict(self.ident, judge_id=self.judge_id, method=self.method)
        b["runtime_version"] = "ollama/%s" % (runtime_ver or self.ollama_version)
        return b

    def describe(self):
        return dict(self.block(self.ollama_version), backend=self.pin["backend"], endpoint=self.endpoint,
                    flags=self.flags, flags_sha256=self.flags_sha256, config=JG.CONFIG,
                    config_sha256=self.config_sha256, server_config=self.server, server_sha256=self.server_sha256,
                    model_details=self.model_details)

    def build(self, view, inp):
        return JG.BUILDERS[self.method](view, inp, self.template)

    def call(self, call):
        data, err, wall = LC.ollama_generate(self.endpoint, self.pin["model"], self.template["system"], call["prompt"],
                                             call["schema"], self.options, self.pin.get("keep_alive"),
                                             int(self.pin.get("timeout_s", 900)))
        if err is not None:
            return {"status": "timeout" if LC.is_timeout(err) else "judge_error", "error": err, "duration_ms": wall,
                    "cost_usd": 0.0, "cli_version": self.ollama_version}
        res = parse_judge_response(data, self.pin["model"], self.options, JG.make_validator(call))
        res["duration_ms"] = wall
        res["server_ms"] = (data.get("total_duration") or 0) // 1000000
        res["transcript"] = canonical_json(res.pop("meta"))
        res["exit_code"] = 0
        res["cli_version"] = self.ollama_version
        return res


def load_local_pin(path=LOCAL_PIN_PATH):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ── evaluator rows and dev scoring ──

def judge_rows(store_root, run=0):
    """Store -> evaluate_v5.py --judge rows (same shape as run_checks_v5 judge-rows; usd 0)."""
    recs = {}
    for e in JG._read_jsonl(os.path.join(store_root, "index", "records.jsonl")):
        with open(os.path.join(store_root, "records", e["record_id"] + ".json"), encoding="utf-8") as fh:
            r = json.load(fh)
        recs[(r["method"], r["item_id"])] = r
    tel = {}
    lp = os.path.join(store_root, "log", "calls.jsonl")
    for e in (JG._read_jsonl(lp) if os.path.exists(lp) else []):
        if e.get("cached") is False and not e.get("regenerate"):
            tel.setdefault(e["cache_key"], e)
    rows = []
    for (m, iid), r in sorted(recs.items()):
        t = tel.get(r["cache_key"]) or {}
        u = t.get("usage") or {}
        rows.append({"id": iid, "method": m, "run": run, "status": r["status"],
                     "selected": r["answer"] if r["status"] in ("ok", "forced") else None,
                     "input_tokens": u.get("input_tokens", 0) or 0, "output_tokens": u.get("output_tokens", 0) or 0,
                     "usd": 0.0, "wall_ms": t.get("duration_ms") or 0})
    return rows


def load_evaluate():
    spec = importlib.util.spec_from_file_location("evaluate_v5", os.path.join(V5, "evaluate_v5.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def score(rows, items_path, paired_csv, inputs_path):
    """Dev accuracy on the given rows' items, mirroring evaluate_v5: J correct iff its selected value
    canonicalises to a proposed value that G-AK grades correct; a non-ok J falls back to MAJ
    (J_fallback). RS correct iff its answer canonicalises and G-AK grades it correct; non-ok RS is
    wrong. Also: how often J picks the answer of the participant agent `mistral` (self-preference)."""
    EV = load_evaluate()
    items = EV.load_items(items_path)
    maj = {}
    with open(paired_csv, newline="") as fh:
        for r in csv.DictReader(fh):
            maj[r["id"]] = r
    inputs = {d["item_id"]: d for d in JG._read_jsonl(inputs_path)}
    out = {}
    for m in ("J", "RS"):
        rs = [r for r in rows if r["method"] == m]
        if not rs:
            continue
        n = len(rs)
        corr, fb, by_src, self_pick, mistral_right = 0, 0, {}, [0, 0], [0, 0]
        st = {}
        for r in rs:
            it = items[r["id"]]
            st[r["status"]] = st.get(r["status"], 0) + 1
            src = it["source"]["key"]
            sel = r["selected"] if r["status"] in ("ok", "forced") else None
            if m == "J":
                proposed = {}
                for a in inputs[r["id"]]["agents"]:
                    if a.get("parsed") and a.get("answer") is not None:
                        cv = EV.canonical_of(it, a["answer"])
                        if cv is not None:
                            proposed.setdefault(cv, (a["answer"], set()))[1].add(a["agent_id"])
                cv = EV.canonical_of(it, sel) if sel else None
                if cv is None or cv not in proposed:
                    ok = int(maj[r["id"]]["MAJ"])
                    fb += 1
                else:
                    ok = int(EV.grade_value(it, cv, proposed[cv][0]))
                    mist = [k for k, (_, ags) in proposed.items() if "mistral" in ags]
                    if mist:
                        self_pick[1] += 1
                        self_pick[0] += int(cv == mist[0])
                        mistral_right[1] += 1
                        mistral_right[0] += int(EV.grade_value(it, mist[0], proposed[mist[0]][0]))
            else:
                cv = EV.canonical_of(it, sel) if sel else None
                ok = int(cv is not None and EV.grade_value(it, cv, sel))
            corr += ok
            b = by_src.setdefault(src, [0, 0])
            b[0] += ok
            b[1] += 1
        res = {"n": n, "correct": corr, "accuracy": round(corr / n, 4), "accuracy_wilson95": wilson(corr, n),
               "status": st, "by_source": {k: {"correct": v[0], "n": v[1], "accuracy": round(v[0] / v[1], 4)}
                                           for k, v in sorted(by_src.items())}}
        if m == "J":
            res["fallback_to_MAJ"] = fb
            res["picks_mistral_agent_value"] = {"k": self_pick[0], "n": self_pick[1],
                                                "note": "items where agent mistral proposed a value"}
            res["mistral_agent_value_correct"] = {"k": mistral_right[0], "n": mistral_right[1]}
        out[m] = res
    return out


def wilson(k, n, z=1.959964):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return [round(c - h, 4), round(c + h, 4)]


# ── command line ──

def cmd_run(args):
    if "v4/results/conf" in os.path.abspath(args.inputs).replace("\\", "/"):
        raise SystemExit("refused: v4 confirmatory data are blinded")
    judge = LocalJudge(args.method)
    if args.expect_judge and judge.judge_id != args.expect_judge:
        raise SystemExit("ABORT: judge_id %s != expected %s" % (judge.judge_id, args.expect_judge))
    store = JG.JudgeStore(args.out)
    items = {it["id"]: it for it in JG._read_jsonl(args.items)}
    inputs = JG._read_jsonl(args.inputs)
    if args.limit:
        inputs = inputs[:args.limit]
    if args.reverse:
        inputs = inputs[::-1]
    res = JG.run_batch(judge, store, items, inputs, workers=args.workers, regenerate=args.regenerate,
                       offline=args.offline)
    for r in res:
        print(canonical_json({"item_id": r["telemetry"]["item_id"], "record_id": r["record_id"],
                              "status": r["status"], "answer": (r["record"] or {}).get("answer")}))
    print(json.dumps(dict(JG.summarize_log(os.path.join(store.root, "log", "calls.jsonl")), judge_id=judge.judge_id),
                     sort_keys=True), file=sys.stderr)
    return 0


def cmd_rows(args):
    rows = judge_rows(args.store)
    if args.ids:
        keep = {l.strip() for l in open(args.ids) if l.strip()}
        rows = [r for r in rows if r["id"] in keep]
    with open(args.out_file, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
    print(json.dumps({"rows": len(rows)}))
    return 0


def cmd_score(args):
    rows = JG._read_jsonl(args.rows)
    print(json.dumps(score(rows, args.items, args.paired_csv, args.inputs), indent=1, sort_keys=True))
    return 0


def cmd_id(args):
    for m in JG.METHODS:
        print(json.dumps(LocalJudge(m).describe(), indent=1, sort_keys=True))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("run")
    c.add_argument("--method", required=True, choices=JG.METHODS)
    c.add_argument("--items", required=True)
    c.add_argument("--inputs", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--limit", type=int, default=0)
    c.add_argument("--workers", type=int, default=1, help="OLLAMA_NUM_PARALLEL is 1: more workers only queue")
    c.add_argument("--regenerate", action="store_true")
    c.add_argument("--offline", action="store_true")
    c.add_argument("--reverse", action="store_true", help="process inputs in reverse order (determinism check)")
    c.add_argument("--expect-judge", default="")
    c.set_defaults(fn=cmd_run)
    r = sub.add_parser("rows", help="store -> evaluate_v5.py --judge JSONL")
    r.add_argument("--store", required=True)
    r.add_argument("--ids")
    r.add_argument("--out-file", required=True)
    r.set_defaults(fn=cmd_rows)
    s = sub.add_parser("score", help="dev accuracy of judge rows (v5 dev only)")
    s.add_argument("--rows", required=True)
    s.add_argument("--items", default=os.path.join(V5, "benchmark", "items_dev.jsonl"))
    s.add_argument("--paired-csv", default=os.path.join(V5, "results", "dev", "eval", "paired_decisions_v5.csv"))
    s.add_argument("--inputs", default=os.path.join(V5, "results", "dev", "judge_inputs_decisive.jsonl"))
    s.set_defaults(fn=cmd_score)
    sub.add_parser("judge-id").set_defaults(fn=cmd_id)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
