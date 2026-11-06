#!/usr/bin/env python3
"""Closed-book Sonnet reference CB-S for eval v5 -> bran-judge/1 (PREREGISTRATION.md §2.4, §5.1).

CB-S sees the question and, for multiple-choice items, the options; nothing else: no agent
answers, no confidences, no passages. Its answer is constrained to the item's answer_schema
(an enum for letter / SUPPORTED-REFUTED items, a short free string for PopQA) and graded by
G-AK directly in evaluate_v5.py (a null answer is scored wrong). It quantifies memorisation of
these public benchmarks (FRAMING O2); outside knowledge is the point.

Everything but the prompt is judge.py's, unchanged and imported (judge.py, prompt_J.txt and
prompt_RS.txt are frozen; J and RS keep their judge ids):
  * the gold-blind item view (judge.item_view) and the task block (judge.render_task, with the
    checker's neutralizer), the answer-format instruction and schema of RS (same rule, no
    passages), the response schema {answer, confidence};
  * the hosted pin (pin.json: claude -p --model claude-sonnet-5-5, effort low, all tools off,
    budget cap) and its CLI flags (judge.cli_flags), the strict output parser, the decision
    cache (cache_key over judge_id, method, prompt, schema), the store, sealed canonical records,
    the call log and --regenerate drift logging.

Identity: judge_id = judge.compute_judge_id over {model, model_digest, prompt_template_sha256
(prompt_CBS.txt), decoding, judge_tool_version}; judge_tool_version binds this file, judge.py,
the template, the CLI flags and CBS_CONFIG. The CLI version is recorded per call
(runtime_version), as for J and RS; the prereg pins it operationally at 2.1.307.

Usage (python3 -I):
  closed_book.py judge-id
  closed_book.py render --items items.jsonl --ids ids.txt [--limit N]
  closed_book.py run    --items items.jsonl --ids ids.txt --out <store> [--workers 4] [--regenerate] [--offline]
  closed_book.py rows   --store <store> --out-file cbs_rows.jsonl [--run 0]   # evaluate_v5.py --judge rows
  closed_book.py cost   --out <store>
`--inputs <bran-judge-input/1 JSONL>` may replace `--ids` (only item_id is read).
"""

import argparse
import concurrent.futures
import json
import os
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import judge as JG  # noqa: E402
from canonical import canonical_bytes, canonical_json, sha256_hex, git_blob_sha1  # noqa: E402

METHOD = "CB-S"
CBS_SEMVER = "0.1.0"
TEMPLATE_FILE = "prompt_CBS.txt"
PLACEHOLDERS = ("task", "answer_instruction")
# Fixed configuration; hashed into judge_tool_version, so into judge_id.
CBS_CONFIG = {
    "context": "closed_book",          # question and options only
    "max_prompt_chars": 40000,
    "max_free_answer_chars": 60,       # PopQA answer_schema maxLength (as judge.CONFIG)
    "schema_generator": "1",
}


def load_template(path=None):
    path = path or os.path.join(HERE, TEMPLATE_FILE)
    with open(path, "rb") as fh:
        raw = fh.read()
    m = re.match(r"=== SYSTEM ===\n(.*?)\n=== USER ===\n(.*)\Z", raw.decode("utf-8"), re.S)
    if not m:
        raise ValueError("template must have === SYSTEM === and === USER === sections")
    user = m.group(2)
    for n in PLACEHOLDERS:
        if user.count("{%s}" % n) != 1:
            raise ValueError("template CB-S must contain {%s} exactly once" % n)
        if ("{%s}" % n) in m.group(1):
            raise ValueError("SYSTEM section must be item-independent")
    return {"system": m.group(1), "user": user, "sha256": sha256_hex(raw), "file": os.path.basename(path)}


def _sub(template_user, vals):
    return re.sub(r"\{(%s)\}" % "|".join(PLACEHOLDERS), lambda m: vals[m.group(1)], template_user)


def build_CBS(view, inp, template):
    """-> call dict (judge.py shape). `inp` is optional; if given, only its item_id is read."""
    if inp is not None and inp.get("item_id") != view["id"]:
        raise JG.InputError("input item_id %r != item %r" % (inp.get("item_id"), view["id"]))
    sch = view["answer_schema"]
    if "enum" in sch:
        allowed_disp = list(sch["enum"])
        allowed_map = {v: v for v in allowed_disp}
        instr = "ANSWER FORMAT: answer must be exactly one of %s." % json.dumps(allowed_disp, ensure_ascii=False)
        ans_schema = {"type": "string", "enum": allowed_disp}
        allowed, free = list(allowed_disp), False
    else:
        n = min(sch["maxLength"], CBS_CONFIG["max_free_answer_chars"])
        instr = ("ANSWER FORMAT: answer is the short answer only (a name or value, at most %d characters), "
                 "no explanation." % n)
        ans_schema = {"type": "string", "minLength": 1, "maxLength": n}
        allowed_map, allowed, free = None, {"type": "string", "maxLength": n}, True
    prompt = _sub(template["user"], {"task": JG.render_task(view), "answer_instruction": instr})
    return {"method": METHOD, "status": None, "prompt": prompt, "schema": JG.response_schema(ans_schema),
            "allowed_map": allowed_map, "allowed": allowed, "inputs": {"context": "closed_book"},
            "forced_value": None, "free_answer": free}


def _blob(path):
    with open(path, "rb") as fh:
        return git_blob_sha1(fh.read())[:12]


class ClosedBookJudge:
    """Duck-type compatible with judge.Judge (argv / call / block are judge.Judge's own)."""

    argv = JG.Judge.argv
    call = JG.Judge.call
    block = JG.Judge.block

    def __init__(self, claude_bin=JG.DEFAULT_CLAUDE, pin=None, template=None, workdir=None):
        self.method = METHOD
        self.claude_bin = claude_bin
        self.pin = pin or JG.load_pin()
        self.template = template or load_template()
        self.flags = JG.cli_flags(self.pin)
        self.workdir = workdir or tempfile.mkdtemp(prefix="bran-cbs-")
        self.flags_sha256 = sha256_hex(canonical_bytes({"backend": self.pin["backend"], "flags": self.flags}))
        self.config_sha256 = sha256_hex(canonical_bytes(CBS_CONFIG))
        self.tool_version = "%s-cbs%s+%s.%s.%s.f%s.c%s" % (
            JG.SEMVER, CBS_SEMVER, _blob(os.path.abspath(__file__)), _blob(os.path.join(HERE, "judge.py")),
            _blob(os.path.join(HERE, self.template["file"])), self.flags_sha256[:12], self.config_sha256[:12])
        self.ident = {
            "model": self.pin["model"],
            "model_digest": self.pin.get("model_digest") or JG.check.HOSTED_MODEL_DIGEST,
            "prompt_template_sha256": self.template["sha256"],
            "decoding": dict(JG.check.DECODING),
            "judge_tool_version": self.tool_version,
        }
        self.judge_id = JG.compute_judge_id(self.ident)

    def describe(self, cli_ver=None):
        return dict(self.block(cli_ver), backend=self.pin["backend"], flags=self.flags, flags_sha256=self.flags_sha256,
                    config=CBS_CONFIG, config_sha256=self.config_sha256, template_file=self.template["file"])

    def build(self, view, inp=None):
        return build_CBS(view, inp, self.template)


def build_record(judge, view, call, key, prompt_sha, entry):
    ok = entry["status"] == "ok"
    return {
        "format": JG.FORMAT,
        "method": METHOD,
        "item_id": view["id"],
        "item_view_sha256": sha256_hex(canonical_bytes(view)),
        "judge": judge.block(entry.get("cli_version")),
        "order": {"seed": None, "rule": "closed book: no agent answers, no passages"},
        "inputs": call["inputs"],
        "allowed": call["allowed"],
        "prompt_sha256": prompt_sha,
        "response_schema_sha256": sha256_hex(canonical_bytes(call["schema"])),
        "cache_key": key,
        "status": entry["status"],
        "answer": entry["answer"] if ok else None,
        "confidence": entry["confidence"] if ok else None,
        "raw_output_sha256": entry["raw_output_sha256"],
    }


def decide(judge, store, item, inp=None, regenerate=False, offline=False):
    """judge.decide's contract (cache, transient failures unsealed, --regenerate logged against the
    authoritative decision) for CB-S."""
    view = JG.item_view(item)
    call = judge.build(view, inp)
    key = JG.cache_key(judge, call)
    prompt_sha = store.put_prompt(call["prompt"])
    tel = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "method": METHOD, "item_id": view["id"],
           "cache_key": key, "judge_id": judge.judge_id, "prompt_chars": len(call["prompt"]),
           "regenerate": bool(regenerate)}
    if len(call["prompt"]) > CBS_CONFIG["max_prompt_chars"]:
        entry = store.put_decision(key, JG._entry(key, {"status": "input_too_long"}, sha256_hex(b""), None))
        tel["cached"] = None
    else:
        hit = store.get(key)
        if hit and not regenerate:
            entry = hit
            tel["cached"] = True
        elif offline:
            return {"record_id": None, "record": None, "status": "uncached", "cached": False, "telemetry": tel}
        else:
            res = judge.call(call)
            raw_sha, tr_sha = store.put_raw(res) if res["status"] != "timeout" else (sha256_hex(b""), None)
            fresh = JG._entry(key, res, raw_sha, res.get("cli_version"))
            tel.update(cached=False, status=res["status"], duration_ms=res.get("duration_ms"),
                       cost_usd=res.get("cost_usd"), usage=res.get("usage"), exit_code=res.get("exit_code"),
                       transcript_sha256=tr_sha, cli_version=res.get("cli_version"))
            if regenerate and hit is not None:
                store.log("log/calls.jsonl", dict(tel, status=fresh["status"]))
                agree = hit["status"] == fresh["status"] and hit["answer"] == fresh["answer"]
                store.log("log/regen.jsonl", {
                    "method": METHOD, "item_id": view["id"], "cache_key": key,
                    "authoritative": {"status": hit["status"], "answer": hit["answer"]},
                    "regen": {"status": fresh["status"], "answer": fresh["answer"], "raw_output_sha256": raw_sha},
                    "agree": agree})
                return {"record_id": None, "record": None, "status": fresh["status"], "cached": False,
                        "telemetry": tel, "regen": fresh, "authoritative": hit, "agree": agree}
            if res["status"] not in JG.CACHEABLE:
                store.log("log/calls.jsonl", tel)
                return {"record_id": None, "record": None, "status": res["status"], "cached": False, "telemetry": tel}
            entry = store.put_decision(key, fresh)
    tel["status"] = entry["status"]
    store.log("log/calls.jsonl", tel)
    rec = build_record(judge, view, call, key, prompt_sha, entry)
    rid = store.put_record(rec)
    return {"record_id": rid, "record": rec, "status": entry["status"], "cached": tel.get("cached"), "telemetry": tel}


def run_batch(judge, store, items_by_id, ids, workers=4, regenerate=False, offline=False):
    def one(iid):
        it = items_by_id.get(iid)
        if it is None:
            raise JG.InputError("no item %s" % iid)
        return decide(judge, store, it, {"item_id": iid}, regenerate=regenerate, offline=offline)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return list(ex.map(one, ids))


def judge_rows(store_root, run=0):
    """Store -> evaluate_v5.py --judge rows. input_tokens counts uncached + cache-creation +
    cache-read tokens, as run_checks_v5.judge_rows does for J / RS; the cache tokens are also
    given separately (prereg §7: cache-creation tokens shown separately)."""
    recs = {}
    for e in JG._read_jsonl(os.path.join(store_root, "index", "records.jsonl")):
        with open(os.path.join(store_root, "records", e["record_id"] + ".json"), encoding="utf-8") as fh:
            r = json.load(fh)
        if r["method"] == METHOD:
            recs[r["item_id"]] = r
    tel = {}
    lp = os.path.join(store_root, "log", "calls.jsonl")
    for e in (JG._read_jsonl(lp) if os.path.exists(lp) else []):
        if e.get("cached") is False and not e.get("regenerate"):
            tel.setdefault(e["cache_key"], e)
    rows = []
    for iid, r in sorted(recs.items()):
        t = tel.get(r["cache_key"]) or {}
        u = t.get("usage") or {}
        rows.append({"id": iid, "method": METHOD, "run": run, "status": r["status"],
                     "selected": r["answer"] if r["status"] == "ok" else None,
                     "input_tokens": sum(u.get(k, 0) or 0 for k in (
                         "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
                     "cache_creation_input_tokens": u.get("cache_creation_input_tokens", 0) or 0,
                     "cache_read_input_tokens": u.get("cache_read_input_tokens", 0) or 0,
                     "output_tokens": u.get("output_tokens", 0) or 0, "usd": t.get("cost_usd") or 0.0,
                     "wall_ms": t.get("duration_ms") or 0, "judge_id": r["judge"]["judge_id"],
                     "model": r["judge"]["model"], "runtime_version": r["judge"].get("runtime_version")})
    return rows


# ── command line ──

def _ids(args):
    if args.ids:
        with open(args.ids, encoding="utf-8") as fh:
            ids = [l.strip() for l in fh if l.strip()]
    else:
        ids = [e["item_id"] for e in JG._read_jsonl(args.inputs)]
    ids = list(dict.fromkeys(ids))
    return ids[:args.limit] if args.limit else ids


def cmd_run(args):
    judge = ClosedBookJudge(claude_bin=args.claude_bin)
    store = JG.JudgeStore(args.out)
    items = {it["id"]: it for it in JG._read_jsonl(args.items)}
    res = run_batch(judge, store, items, _ids(args), workers=args.workers, regenerate=args.regenerate,
                    offline=args.offline)
    for r in res:
        print(canonical_json({"item_id": r["telemetry"]["item_id"], "record_id": r["record_id"],
                              "status": r["status"], "answer": (r["record"] or {}).get("answer")}))
    print(json.dumps(JG.summarize_log(os.path.join(store.root, "log", "calls.jsonl")), sort_keys=True), file=sys.stderr)
    return 0


def cmd_render(args):
    judge = ClosedBookJudge(claude_bin=args.claude_bin)
    items = {it["id"]: it for it in JG._read_jsonl(args.items)}
    for iid in _ids(args):
        call = judge.build(JG.item_view(items[iid]), {"item_id": iid})
        print("##### CB-S %s schema=%s\n%s\n" % (iid, json.dumps(call["schema"]), call["prompt"]))
    return 0


def cmd_id(args):
    j = ClosedBookJudge(claude_bin=args.claude_bin)
    print(json.dumps(j.describe(JG.check.cli_version(args.claude_bin) if args.with_cli else None), indent=1,
                     sort_keys=True))
    return 0


def cmd_rows(args):
    rows = judge_rows(args.store, run=args.run)
    with open(args.out_file, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
    print(json.dumps({"rows": len(rows)}))
    return 0


def cmd_cost(args):
    print(json.dumps(JG.summarize_log(os.path.join(args.out, "log", "calls.jsonl")), indent=1, sort_keys=True))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--claude-bin", default=JG.DEFAULT_CLAUDE)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("run", cmd_run), ("render", cmd_render)):
        c = sub.add_parser(name)
        c.add_argument("--items", required=True, help="benchmark items JSONL (read gold-blind)")
        g = c.add_mutually_exclusive_group(required=True)
        g.add_argument("--ids", help="item ids, one per line")
        g.add_argument("--inputs", help="bran-judge-input/1 JSONL (only item_id is read)")
        c.add_argument("--limit", type=int, default=0)
        if name == "run":
            c.add_argument("--out", required=True, help="judge store root")
            c.add_argument("--workers", type=int, default=4)
            c.add_argument("--regenerate", action="store_true", help="drift run: fresh call, logged, cache unchanged")
            c.add_argument("--offline", action="store_true", help="replay from cache only, never call the model")
        c.set_defaults(fn=fn)
    i = sub.add_parser("judge-id")
    i.add_argument("--with-cli", action="store_true", help="also record the installed CLI version")
    i.set_defaults(fn=cmd_id)
    r = sub.add_parser("rows", help="store -> evaluate_v5.py --judge JSONL (method CB-S)")
    r.add_argument("--store", required=True)
    r.add_argument("--out-file", required=True)
    r.add_argument("--run", type=int, default=0)
    r.set_defaults(fn=cmd_rows)
    c = sub.add_parser("cost")
    c.add_argument("--out", required=True)
    c.set_defaults(fn=cmd_cost)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
