#!/usr/bin/env python3
"""LLM judge baseline J and evidence-only reader RS for eval v5 -> bran-judge/1.

Design: v3/SWARM3_DESIGN.md §5 (methods J, RS), §5.2 (judge), §5.3, §7.2-§7.3.

  J   The judge model sees the question (and options), then every parsed agent
      answer with the full text of the passages that agent cited, and picks one
      of the values the agents proposed (JSON output constrained to them).
  RS  The same model sees the question (and options) and the union of the
      passages the agents were shown, with no agent answers, and answers it
      (constrained to the item's answer schema).

Both use the support checker's model pin and CLI invocation
(tools/evidence/support/check.py): `claude -p --model claude-sonnet-5-5`,
effort low, all tools off, no MCP, --safe-mode, no setting sources, no slash
commands, no session persistence, budget cap, empty working directory, prompt
on stdin, fixed argv (no shell). Untrusted text (question, options, agent
answers, passages) is placed only between fixed delimiters after the
checker's neutralizer, so it cannot open or close a delimiter.

Determinism of the inputs:
  * Gold-blind item view: only id, item_type, answer_format, answer_schema,
    question, option letters/texts and source.key are read (never gold,
    gold_triples, options[].correct, source.label, ...).
  * J candidate order: agents sorted by agent_id, then
    random.Random("v5-judge:" + item_id).shuffle. Agents are shown as
    "Agent 1..n" by position; model names are never shown.
  * RS passage order: de-duplicated by passage_key, sorted, then
    random.Random("v5-rs:" + item_id).shuffle.
  * The allowed-answer enum is the sorted set of proposed values.

Decisions are cached by cache_key = sha256_hex16(judge_id, method,
prompt_sha256, response_schema_sha256), so nothing is re-queried; the first
cached answer is authoritative and --regenerate (drift measurement) logs a
fresh answer next to it without replacing it. Every decision is sealed as a
canonical-JSON record whose id is sha256_hex16 of its bytes. Cost and latency
go to log/calls.jsonl, outside the sealed record.

Stdlib only. Run with `python3 -I`.
"""

import argparse
import concurrent.futures
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
SUPPORT = os.path.join(TOOLS, "evidence", "support")
sys.path.insert(0, os.path.join(TOOLS, "evidence"))
sys.path.insert(0, SUPPORT)
import check  # noqa: E402  (neutralize, cli_version, hosted-model constants, checker pin)
from canonical import canonical_bytes, canonical_json, record_id, sha256_hex, sha256_hex16, git_blob_sha1  # noqa: E402

FORMAT = "bran-judge/1"
INPUT_FORMAT = "bran-judge-input/1"
SEMVER = "0.1.0"
METHODS = ("J", "RS")
TEMPLATE_FILES = {"J": "prompt_J.txt", "RS": "prompt_RS.txt"}
PLACEHOLDERS = {"J": ("task", "candidates", "allowed"), "RS": ("task", "passages", "answer_instruction")}
SEED_PREFIX = {"J": "v5-judge:", "RS": "v5-rs:"}
PIN_PATH = os.path.join(HERE, "pin.json")
DEFAULT_CLAUDE = check.DEFAULT_CLAUDE

STATUSES = ("ok", "parse_error", "timeout", "input_too_long", "model_mismatch", "refused", "judge_error",
            "forced", "no_candidates")
# cached: deterministic given the inputs, or a genuine model answer (incl. a
# safeguard refusal, which is stable for an input). timeout / judge_error are
# transient: not cached, not sealed, retried on the next run.
CACHEABLE = ("ok", "parse_error", "model_mismatch", "input_too_long", "refused")
# decided without a model call
NO_CALL = ("forced", "no_candidates", "input_too_long")

# Fixed configuration; hashed into judge_tool_version, so into judge_id.
CONFIG = {
    "show_agent_confidence": True,   # BE also uses the confidence field
    "include_reasoning": False,      # BE never reads agent reasoning
    "rs_passage_set": "shown",       # union of all passages shown to agents ("cited" = only cited ones)
    "max_passage_chars": 1000,       # corpus passages are <= 1000 chars (§2.2); guard only
    "max_prompt_chars": 40000,
    "max_free_answer_chars": 60,     # PopQA answer_schema maxLength
    "schema_generator": "1",
}
CONFIDENCE_SCHEMA = {"type": "integer", "minimum": 0, "maximum": 10000}
# FEVER page titles carry apostrophes, commas and non-ASCII; reject only control chars.
_KEY_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,400}$")
_LABEL_RE = re.compile(r"^P[1-9][0-9]?$")


class InputError(ValueError):
    pass


# ── gold-blind item view ──

def item_view(item):
    """The only item fields the judge reads. Changing gold, gold_triples,
    options[].correct, source.label, context, ... leaves every byte unchanged."""
    it = item["item_type"]
    v = {"id": item["id"], "item_type": it, "answer_format": item["answer_format"],
         "answer_schema": item["answer_schema"], "question": item["question"],
         "source_key": item["source"]["key"]}
    if it == "multiple_choice":
        v["options"] = [{"letter": o["letter"], "text": o["text"]} for o in item["options"]]
    elif it not in ("binary_claim", "entity"):
        raise InputError("unknown item_type %r" % it)
    sch = v["answer_schema"]
    if "enum" in sch:
        if not sch["enum"] or not all(isinstance(e, str) for e in sch["enum"]):
            raise InputError("bad answer_schema enum")
    elif not (sch.get("type") == "string" and isinstance(sch.get("maxLength"), int)):
        raise InputError("answer_schema must be an enum or a string with maxLength")
    return v


def valid_value(view, value):
    if not isinstance(value, str) or not value.strip():
        return False
    sch = view["answer_schema"]
    if "enum" in sch:
        return value in sch["enum"]
    return len(value) <= sch["maxLength"] and not any(unicodedata.category(c) == "Cc" for c in value)


# ── rendering ──

def _block(tag, body, head=None):
    return "<<<%s%s\n%s\n%s>>>" % (tag, (" " + head) if head else "", body, tag)


def render_task(view):
    q = check.neutralize(view["question"]).strip()
    if view["item_type"] == "multiple_choice":
        opts = "\n".join("%s. %s" % (o["letter"], check.neutralize(o["text"]).strip()) for o in view["options"])
        return "Choose the correct option.\n" + _block("QUESTION", q + "\n\n" + opts)
    if view["item_type"] == "binary_claim":
        return ("Decide whether the CLAIM is SUPPORTED or REFUTED.\n"
                + _block("QUESTION", "CLAIM: " + q))
    return _block("QUESTION", q)


def _passage_text(text):
    return check.neutralize(text)[:CONFIG["max_passage_chars"]]


def _check_key(k):
    if not isinstance(k, str) or not _KEY_RE.match(k):
        raise InputError("bad passage_key %r" % (k,))
    return k


def _sub(template_user, method, vals):
    names = PLACEHOLDERS[method]
    # single pass: substituted values are never re-scanned for placeholders
    return re.sub(r"\{(%s)\}" % "|".join(names), lambda m: vals[m.group(1)], template_user)


def load_template(method, path=None):
    path = path or os.path.join(HERE, TEMPLATE_FILES[method])
    with open(path, "rb") as fh:
        raw = fh.read()
    m = re.match(r"=== SYSTEM ===\n(.*?)\n=== USER ===\n(.*)\Z", raw.decode("utf-8"), re.S)
    if not m:
        raise ValueError("template must have === SYSTEM === and === USER === sections")
    user = m.group(2)
    for n in PLACEHOLDERS[method]:
        if user.count("{%s}" % n) != 1:
            raise ValueError("template %s must contain {%s} exactly once" % (method, n))
        if ("{%s}" % n) in m.group(1):
            raise ValueError("SYSTEM section must be item-independent")
    return {"system": m.group(1), "user": user, "sha256": sha256_hex(raw), "file": os.path.basename(path)}


# ── building one call (pure: no I/O) ──

def _norm_agents(inp):
    if inp.get("format") != INPUT_FORMAT:
        raise InputError("input format must be %s" % INPUT_FORMAT)
    agents = inp.get("agents")
    if not isinstance(agents, list):
        raise InputError("agents must be a list")
    ids = [a.get("agent_id") for a in agents]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise InputError("agent_id must be unique non-empty strings")
    return sorted(agents, key=lambda a: a["agent_id"])


def _shown_map(a):
    out = {}
    for p in a.get("shown") or []:
        lab = p.get("label")
        if not isinstance(lab, str) or not _LABEL_RE.match(lab) or lab in out:
            raise InputError("agent %s: bad or duplicate shown label %r" % (a["agent_id"], lab))
        if not isinstance(p.get("text"), str):
            raise InputError("agent %s: passage %s has no text" % (a["agent_id"], lab))
        out[lab] = {"passage_key": _check_key(p.get("passage_key")), "text": p["text"]}
    return out


def build_J(view, inp, template):
    """-> call dict: {method, status?, prompt, schema, allowed_map, inputs, allowed}"""
    if inp.get("item_id") != view["id"]:
        raise InputError("input item_id %r != item %r" % (inp.get("item_id"), view["id"]))
    cands, excluded = [], []
    for a in _norm_agents(inp):
        if not a.get("parsed") or a.get("answer") is None:
            excluded.append({"agent_id": a["agent_id"], "reason": "unparsed"})
            continue
        if not valid_value(view, a["answer"]):
            excluded.append({"agent_id": a["agent_id"], "reason": "invalid_value"})
            continue
        shown = _shown_map(a)
        cites, invalid, seen = [], [], set()
        for lab in a.get("citations") or []:
            if lab in seen:
                continue
            seen.add(lab)
            if lab not in shown:
                invalid.append(lab)
                continue
            cites.append(dict(shown[lab], label=lab))
        conf = a.get("confidence")
        cands.append({"agent_id": a["agent_id"], "response_id": a.get("response_id"), "value": a["answer"],
                      "confidence": conf if isinstance(conf, str) else None,
                      "reasoning": a.get("reasoning") if isinstance(a.get("reasoning"), str) else None,
                      "citations": cites, "invalid_citations": invalid})
    random.Random(SEED_PREFIX["J"] + view["id"]).shuffle(cands)

    values = sorted({c["value"] for c in cands})
    allowed_map = {}
    for v in values:
        d = check.neutralize(v).strip()
        if not d or d in allowed_map:
            raise InputError("candidate values collide after neutralizing: %r" % v)
        allowed_map[d] = v

    blocks = []
    for pos, c in enumerate(cands, 1):
        lines = ["Agent %d" % pos, _block("ANSWER", check.neutralize(c["value"]).strip())]
        if CONFIG["show_agent_confidence"] and c["confidence"]:
            lines.append("Agent's stated confidence: " + check.neutralize(c["confidence"]).strip()[:20])
        if CONFIG["include_reasoning"] and c["reasoning"]:
            lines.append(_block("REASONING", check.neutralize(c["reasoning"]).strip()))
        if c["citations"]:
            lines.append("Passages this agent cited (%d):" % len(c["citations"]))
            lines += [_block("PASSAGE", _passage_text(p["text"]), p["passage_key"]) for p in c["citations"]]
        else:
            lines.append("Passages this agent cited: none")
        blocks.append("\n".join(lines))
    candidates_txt = "CANDIDATE ANSWERS (%d agents):\n\n%s" % (len(cands), "\n\n".join(blocks))
    allowed_disp = sorted(allowed_map)
    prompt = _sub(template["user"], "J", {"task": render_task(view), "candidates": candidates_txt,
                                         "allowed": json.dumps(allowed_disp, ensure_ascii=False)})
    schema = response_schema({"type": "string", "enum": allowed_disp})
    inputs = {"candidates": [{"position": pos, "agent_id": c["agent_id"], "response_id": c["response_id"],
                              "value": c["value"], "confidence": c["confidence"],
                              "citations": [{"label": p["label"], "passage_key": p["passage_key"],
                                             "text_sha256": sha256_hex(p["text"].encode("utf-8"))}
                                            for p in c["citations"]],
                              "invalid_citations": c["invalid_citations"]}
                             for pos, c in enumerate(cands, 1)],
              "excluded": excluded}
    status = None
    if not values:
        status = "no_candidates"
    elif len(values) == 1:
        status = "forced"
    return {"method": "J", "status": status, "prompt": prompt, "schema": schema, "allowed_map": allowed_map,
            "allowed": values, "inputs": inputs, "forced_value": values[0] if len(values) == 1 else None,
            "free_answer": False}


def build_RS(view, inp, template):
    if inp.get("item_id") != view["id"]:
        raise InputError("input item_id %r != item %r" % (inp.get("item_id"), view["id"]))
    by_key = {}
    for a in _norm_agents(inp):
        shown = _shown_map(a)
        if CONFIG["rs_passage_set"] == "cited":
            labs = [l for l in (a.get("citations") or []) if l in shown] if a.get("parsed") else []
        else:
            labs = list(shown)
        for lab in labs:
            k, t = shown[lab]["passage_key"], shown[lab]["text"]
            if k in by_key and by_key[k] != t:
                raise InputError("passage %s has two different texts" % k)
            by_key[k] = t
    keys = sorted(by_key)
    random.Random(SEED_PREFIX["RS"] + view["id"]).shuffle(keys)
    if keys:
        ptxt = "PASSAGES (%d):\n\n%s" % (len(keys), "\n\n".join(
            _block("PASSAGE", _passage_text(by_key[k]), k) for k in keys))
    else:
        ptxt = "PASSAGES: none were retrieved."
    sch = view["answer_schema"]
    if "enum" in sch:
        allowed_disp = list(sch["enum"])
        allowed_map = {v: v for v in allowed_disp}
        instr = "ANSWER FORMAT: answer must be exactly one of %s." % json.dumps(allowed_disp, ensure_ascii=False)
        ans_schema = {"type": "string", "enum": allowed_disp}
        allowed, free = list(allowed_disp), False
    else:
        n = min(sch["maxLength"], CONFIG["max_free_answer_chars"])
        instr = "ANSWER FORMAT: answer is the short answer only (a name or value, at most %d characters), no explanation." % n
        ans_schema = {"type": "string", "minLength": 1, "maxLength": n}
        allowed_map, allowed, free = None, {"type": "string", "maxLength": n}, True
    prompt = _sub(template["user"], "RS", {"task": render_task(view), "passages": ptxt, "answer_instruction": instr})
    inputs = {"passage_set": CONFIG["rs_passage_set"],
              "passages": [{"position": i, "passage_key": k, "text_sha256": sha256_hex(by_key[k].encode("utf-8"))}
                           for i, k in enumerate(keys, 1)]}
    return {"method": "RS", "status": None, "prompt": prompt, "schema": response_schema(ans_schema),
            "allowed_map": allowed_map, "allowed": allowed, "inputs": inputs, "forced_value": None,
            "free_answer": free}


BUILDERS = {"J": build_J, "RS": build_RS}


def response_schema(answer_schema):
    return {"type": "object", "properties": {"answer": answer_schema, "confidence": dict(CONFIDENCE_SCHEMA)},
            "required": ["answer", "confidence"], "additionalProperties": False}


# ── CLI output parsing ──

def make_validator(call):
    if call["free_answer"]:
        n = call["allowed"]["maxLength"]

        def v(ans):
            a = ans.strip()
            ok = 0 < len(a) <= n and not any(unicodedata.category(c) == "Cc" for c in a)
            return a if ok else None
        return v
    amap = call["allowed_map"]
    return lambda ans: amap.get(ans)


def parse_cli_output(stdout_bytes, pinned_model, validate):
    """Strict parse of `claude -p --output-format json` (result object or event
    array). `validate(answer_display) -> original value or None`. Never raises."""
    out = {"status": "parse_error", "answer": None, "confidence": None, "model_output": None,
           "model_reported": None, "cost_usd": None, "usage": None}
    try:
        doc = json.loads(stdout_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        out["status"] = "judge_error"
        return out
    events = doc if isinstance(doc, list) else [doc]
    result, models = None, []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "result":
            result = ev
        if ev.get("type") == "assistant" and isinstance(ev.get("message"), dict):
            m = ev["message"].get("model")
            if isinstance(m, str) and m not in models:
                models.append(m)
    if result is None:
        out["status"] = "judge_error"
        return out
    out["cost_usd"] = result.get("total_cost_usd")
    u = result.get("usage")
    if isinstance(u, dict):
        out["usage"] = {k: u.get(k) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                              "cache_creation_input_tokens") if isinstance(u.get(k), int)}
    if not models and isinstance(result.get("modelUsage"), dict):
        models = sorted(result["modelUsage"].keys())
    out["model_reported"] = ",".join(models) if models else None
    if result.get("stop_reason") == "refusal":
        out["status"] = "refused"
        mo = result.get("result")
        out["model_output"] = "refusal:" + (mo.split("\n", 1)[0][:200] if isinstance(mo, str) else "")
        return out
    if result.get("is_error") or result.get("subtype") != "success":
        out["status"] = "judge_error"
        return out
    mo = result.get("result")
    out["model_output"] = mo if isinstance(mo, str) else None
    if models != [pinned_model]:
        out["status"] = "model_mismatch"
        return out
    so = result.get("structured_output")
    if so is None and isinstance(mo, str):
        try:
            so = json.loads(mo)
        except ValueError:
            so = None
    if not isinstance(so, dict) or set(so.keys()) != {"answer", "confidence"}:
        return out
    ans, conf = so["answer"], so["confidence"]
    if not isinstance(ans, str) or isinstance(conf, bool) or not isinstance(conf, int) or not 0 <= conf <= 10000:
        return out
    val = validate(ans)
    if val is None:
        return out
    out.update(status="ok", answer=val, confidence=conf,
               model_output=canonical_json({"answer": ans, "confidence": conf}))
    return out


# ── judge identity and invocation ──

def load_pin(path=PIN_PATH):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


SCHEMA_PLACEHOLDER = "@per-call:response_schema"


def cli_flags(pin):
    """Same flags as the support checker (check.cli_flags); --json-schema is
    per call (the allowed enum depends on the item)."""
    return [
        "-p",
        "--model", pin["model"],
        "--output-format", "json",
        "--json-schema", SCHEMA_PLACEHOLDER,
        "--tools", "",
        "--strict-mcp-config",
        "--safe-mode",
        "--setting-sources", "",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--effort", pin["effort"],
        "--max-budget-usd", pin["max_budget_usd"],
        "--system-prompt", "@template#SYSTEM",
    ]


def tool_version(template_file):
    blobs = []
    for p in (os.path.abspath(__file__), os.path.join(HERE, template_file)):
        with open(p, "rb") as fh:
            blobs.append(git_blob_sha1(fh.read())[:12])
    return "%s+%s.%s" % (SEMVER, blobs[0], blobs[1])


def compute_judge_id(block):
    return sha256_hex16(canonical_bytes({k: block[k] for k in (
        "model", "model_digest", "prompt_template_sha256", "decoding", "judge_tool_version")}))


class Judge:
    def __init__(self, method, claude_bin=DEFAULT_CLAUDE, pin=None, template=None, workdir=None, tool_ver=None):
        if method not in METHODS:
            raise ValueError("method must be J or RS")
        self.method = method
        self.claude_bin = claude_bin
        self.pin = pin or load_pin()
        self.template = template or load_template(method)
        self.flags = cli_flags(self.pin)
        self.workdir = workdir or tempfile.mkdtemp(prefix="bran-judge-")
        self.flags_sha256 = sha256_hex(canonical_bytes({"backend": self.pin["backend"], "flags": self.flags}))
        self.config_sha256 = sha256_hex(canonical_bytes(CONFIG))
        self.tool_version = tool_ver or "%s.f%s.c%s" % (tool_version(self.template["file"]),
                                                        self.flags_sha256[:12], self.config_sha256[:12])
        self.ident = {
            "model": self.pin["model"],
            "model_digest": self.pin.get("model_digest") or check.HOSTED_MODEL_DIGEST,
            "prompt_template_sha256": self.template["sha256"],
            "decoding": dict(check.DECODING),
            "judge_tool_version": self.tool_version,
        }
        self.judge_id = compute_judge_id(self.ident)

    def block(self, cli_ver):
        b = dict(self.ident, judge_id=self.judge_id, method=self.method)
        b["runtime_version"] = "claude-code/%s" % (cli_ver or "unknown")
        return b

    def describe(self):
        return dict(self.block(check.cli_version(self.claude_bin)), backend=self.pin["backend"], flags=self.flags,
                    flags_sha256=self.flags_sha256, config=CONFIG, config_sha256=self.config_sha256)

    def build(self, view, inp):
        return BUILDERS[self.method](view, inp, self.template)

    def argv(self, schema):
        a = [self.claude_bin] + list(self.flags)
        a[a.index(SCHEMA_PLACEHOLDER)] = json.dumps(schema, sort_keys=True, separators=(",", ":"))
        a[-1] = self.template["system"]
        return a

    def call(self, call):
        t0 = time.monotonic()
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_SSE") and k != "CLAUDECODE"}
        try:
            cp = subprocess.run(self.argv(call["schema"]), input=call["prompt"].encode("utf-8"), capture_output=True,
                                timeout=int(self.pin.get("timeout_s", 180)), cwd=self.workdir, env=env)
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "duration_ms": int((time.monotonic() - t0) * 1000)}
        except OSError as e:
            return {"status": "judge_error", "error": str(e), "duration_ms": 0}
        res = parse_cli_output(cp.stdout, self.pin["model"], make_validator(call))
        res["duration_ms"] = int((time.monotonic() - t0) * 1000)
        res["exit_code"] = cp.returncode
        res["transcript"] = cp.stdout.decode("utf-8", "replace")
        if cp.returncode != 0 and res["status"] == "ok":
            res["status"] = "judge_error"
        if res["status"] == "judge_error":
            res["stderr"] = cp.stderr.decode("utf-8", "replace")[-2000:]
        res["cli_version"] = check.cli_version(self.claude_bin)
        return res


def cache_key(judge, call):
    return sha256_hex16(canonical_bytes({
        "judge_id": judge.judge_id, "method": judge.method,
        "prompt_sha256": sha256_hex(call["prompt"].encode("utf-8")),
        "response_schema_sha256": sha256_hex(canonical_bytes(call["schema"]))}))


# ── store: decision cache, raw outputs, sealed records, logs ──

class JudgeStore:
    """root/
         decisions.jsonl          cache_key -> decision (first line authoritative)
         raw/<aa>/<sha>.txt       raw model output (sealed by raw_output_sha256)
         transcripts/<aa>/<sha>.json  full CLI stdout (provenance; not sealed)
         prompts/<aa>/<sha>.txt   rendered user prompt (sealed by prompt_sha256)
         records/<record_id>.json sealed bran-judge/1 records
         index/records.jsonl      {method, item_id, record_id}
         log/calls.jsonl          cost / latency / tokens per decision (cached hits too)
         log/regen.jsonl          regeneration (drift) results
    """

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self._lock = threading.Lock()
        self._dec = None

    def _p(self, *parts):
        return os.path.join(self.root, *parts)

    def _write_once(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            with open(path, "rb") as fh:
                if fh.read() != data:
                    raise RuntimeError("existing file differs: %s" % path)
            return
        tmp = "%s.tmp.%d.%d" % (path, os.getpid(), threading.get_ident())
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)

    def _blob(self, kind, data, ext):
        h = sha256_hex(data)
        self._write_once(self._p(kind, h[:2], h + ext), data)
        return h

    def _append(self, rel, line):
        p = self._p(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def decisions(self):
        if self._dec is None:
            self._dec = {}
            p = self._p("decisions.jsonl")
            if os.path.exists(p):
                with open(p, encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            e = json.loads(line)
                            self._dec.setdefault(e["cache_key"], e)
        return self._dec

    def get(self, key):
        with self._lock:
            return self.decisions().get(key)

    def put_prompt(self, prompt):
        with self._lock:
            return self._blob("prompts", prompt.encode("utf-8"), ".txt")

    def put_raw(self, res):
        """Store raw output and transcript; returns (raw_sha, transcript_sha)."""
        with self._lock:
            r = self._blob("raw", (res.get("model_output") or "").encode("utf-8"), ".txt")
            t = self._blob("transcripts", res["transcript"].encode("utf-8"), ".json") if res.get("transcript") else None
            return r, t

    def put_decision(self, key, entry):
        with self._lock:
            if key not in self.decisions():
                self.decisions()[key] = entry
                self._append("decisions.jsonl", canonical_json(entry))
            return self.decisions()[key]

    def put_record(self, rec):
        rid = record_id(rec)
        with self._lock:
            p = self._p("records", rid + ".json")
            new = not os.path.exists(p)
            self._write_once(p, canonical_bytes(rec))
            if new:
                self._append("index/records.jsonl", canonical_json(
                    {"method": rec["method"], "item_id": rec["item_id"], "record_id": rid}))
        return rid

    def log(self, rel, obj):
        with self._lock:
            self._append(rel, json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


# ── one decision ──

def _entry(key, res, raw_sha, cli_ver):
    return {"cache_key": key, "status": res["status"], "answer": res.get("answer"),
            "confidence": res.get("confidence"), "raw_output_sha256": raw_sha,
            "model_reported": res.get("model_reported"), "cli_version": cli_ver}


def build_record(judge, view, call, key, prompt_sha, entry):
    ok = entry["status"] in ("ok", "forced")
    return {
        "format": FORMAT,
        "method": judge.method,
        "item_id": view["id"],
        "item_view_sha256": sha256_hex(canonical_bytes(view)),
        "judge": judge.block(entry.get("cli_version")),
        "order": {"seed": SEED_PREFIX[judge.method] + view["id"],
                  "rule": ("agents sorted by agent_id, then random.Random(seed).shuffle" if judge.method == "J"
                           else "passages de-duplicated by passage_key, sorted, then random.Random(seed).shuffle")},
        "inputs": call["inputs"],
        "allowed": call["allowed"],
        "prompt_sha256": prompt_sha,
        "response_schema_sha256": sha256_hex(canonical_bytes(call["schema"])),
        "cache_key": key,
        "status": entry["status"],
        "answer": entry["answer"] if ok else None,
        "confidence": entry["confidence"] if entry["status"] == "ok" else None,
        "raw_output_sha256": entry["raw_output_sha256"],
    }


def decide(judge, store, item, inp, regenerate=False, offline=False):
    """Run (or reuse) one decision and seal it.
    Returns {record_id, record, status, cached, telemetry}; record_id is None
    for a transient failure (not sealed; retry later) and for regeneration.
    regenerate=True with a cached decision: fresh call, logged to log/regen.jsonl
    against the authoritative one, cache unchanged, nothing sealed (without a
    cached decision it is an ordinary first call).
    offline=True never calls the model (replay from cache; a miss -> 'uncached')."""
    view = item_view(item)
    call = judge.build(view, inp)
    key = cache_key(judge, call)
    prompt_sha = store.put_prompt(call["prompt"])
    tel = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "method": judge.method, "item_id": view["id"],
           "cache_key": key, "judge_id": judge.judge_id, "prompt_chars": len(call["prompt"]),
           "regenerate": bool(regenerate)}
    res = None
    if call["status"] in ("forced", "no_candidates"):
        entry = {"cache_key": key, "status": call["status"], "answer": call["forced_value"], "confidence": None,
                 "raw_output_sha256": sha256_hex(b""), "model_reported": None, "cli_version": None}
        tel["cached"] = None
    elif len(call["prompt"]) > CONFIG["max_prompt_chars"]:
        entry = store.put_decision(key, _entry(key, {"status": "input_too_long"}, sha256_hex(b""), None))
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
            fresh = _entry(key, res, raw_sha, res.get("cli_version"))
            tel.update(cached=False, status=res["status"], duration_ms=res.get("duration_ms"),
                       cost_usd=res.get("cost_usd"), usage=res.get("usage"), exit_code=res.get("exit_code"),
                       transcript_sha256=tr_sha)
            if regenerate and hit is not None:
                store.log("log/calls.jsonl", dict(tel, status=fresh["status"]))
                agree = hit["status"] == fresh["status"] and hit["answer"] == fresh["answer"]
                store.log("log/regen.jsonl", {
                    "method": judge.method, "item_id": view["id"], "cache_key": key,
                    "authoritative": {"status": hit["status"], "answer": hit["answer"]},
                    "regen": {"status": fresh["status"], "answer": fresh["answer"], "raw_output_sha256": raw_sha},
                    "agree": agree})
                return {"record_id": None, "record": None, "status": fresh["status"], "cached": False,
                        "telemetry": tel, "regen": fresh, "authoritative": hit, "agree": agree}
            if res["status"] not in CACHEABLE:
                store.log("log/calls.jsonl", tel)
                return {"record_id": None, "record": None, "status": res["status"], "cached": False, "telemetry": tel}
            entry = store.put_decision(key, fresh)
    tel["status"] = entry["status"]
    store.log("log/calls.jsonl", tel)
    rec = build_record(judge, view, call, key, prompt_sha, entry)
    rid = store.put_record(rec)
    return {"record_id": rid, "record": rec, "status": entry["status"], "cached": tel.get("cached"), "telemetry": tel}


def run_batch(judge, store, items_by_id, inputs, workers=4, regenerate=False, offline=False):
    """Results in input order regardless of completion order."""
    def one(inp):
        it = items_by_id.get(inp["item_id"])
        if it is None:
            raise InputError("no item %s" % inp["item_id"])
        return decide(judge, store, it, inp, regenerate=regenerate, offline=offline)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return list(ex.map(one, inputs))


# ── cost / latency summary ──

def summarize_log(path):
    rows = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            rows = [json.loads(l) for l in fh if l.strip()]
    called = [r for r in rows if r.get("cached") is False]
    lat = sorted(r["duration_ms"] for r in called if isinstance(r.get("duration_ms"), int))
    cost = [r["cost_usd"] for r in called if isinstance(r.get("cost_usd"), (int, float))]

    def q(p):
        return lat[min(len(lat) - 1, int(p * len(lat)))] if lat else None
    tok = {}
    for r in called:
        for k, v in (r.get("usage") or {}).items():
            tok[k] = tok.get(k, 0) + v
    by_status = {}
    for r in rows:
        by_status[r.get("status")] = by_status.get(r.get("status"), 0) + 1
    return {"decisions": len(rows), "model_calls": len(called),
            "cache_hits": sum(1 for r in rows if r.get("cached") is True),
            "no_call": sum(1 for r in rows if r.get("cached") is None),
            "by_status": by_status, "total_cost_usd": round(sum(cost), 6),
            "mean_cost_usd": round(sum(cost) / len(cost), 6) if cost else None,
            "latency_ms": {"mean": int(sum(lat) / len(lat)) if lat else None, "p50": q(0.5), "p95": q(0.95),
                           "max": lat[-1] if lat else None},
            "tokens": tok}


# ── command line ──

def _read_jsonl(p):
    with open(p, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def cmd_run(args):
    judge = Judge(args.method, claude_bin=args.claude_bin)
    store = JudgeStore(args.out)
    items = {it["id"]: it for it in _read_jsonl(args.items)}
    inputs = _read_jsonl(args.inputs)
    if args.limit:
        inputs = inputs[:args.limit]
    res = run_batch(judge, store, items, inputs, workers=args.workers, regenerate=args.regenerate,
                    offline=args.offline)
    for r in res:
        print(canonical_json({"item_id": r["telemetry"]["item_id"], "record_id": r["record_id"],
                              "status": r["status"], "answer": (r["record"] or {}).get("answer")}))
    print(json.dumps(summarize_log(os.path.join(store.root, "log", "calls.jsonl")), sort_keys=True), file=sys.stderr)
    return 0


def cmd_render(args):
    judge = Judge(args.method, claude_bin=args.claude_bin)
    items = {it["id"]: it for it in _read_jsonl(args.items)}
    for inp in _read_jsonl(args.inputs)[:args.limit or None]:
        call = judge.build(item_view(items[inp["item_id"]]), inp)
        print("##### %s %s status=%s schema=%s\n%s\n" % (args.method, inp["item_id"], call["status"],
                                                          json.dumps(call["schema"]), call["prompt"]))
    return 0


def cmd_id(args):
    for m in METHODS:
        print(json.dumps(Judge(m, claude_bin=args.claude_bin).describe(), indent=1, sort_keys=True))
    return 0


def cmd_cost(args):
    print(json.dumps(summarize_log(os.path.join(args.out, "log", "calls.jsonl")), indent=1, sort_keys=True))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--claude-bin", default=DEFAULT_CLAUDE)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("run", cmd_run), ("render", cmd_render)):
        c = sub.add_parser(name)
        c.add_argument("--method", required=True, choices=METHODS)
        c.add_argument("--items", required=True, help="benchmark items JSONL (read gold-blind)")
        c.add_argument("--inputs", required=True, help="bran-judge-input/1 JSONL")
        c.add_argument("--limit", type=int, default=0)
        if name == "run":
            c.add_argument("--out", required=True, help="judge store root")
            c.add_argument("--workers", type=int, default=4)
            c.add_argument("--regenerate", action="store_true", help="drift run: fresh call, logged, cache unchanged")
            c.add_argument("--offline", action="store_true", help="replay from cache only, never call the model")
        c.set_defaults(fn=fn)
    i = sub.add_parser("judge-id")
    i.set_defaults(fn=cmd_id)
    c = sub.add_parser("cost")
    c.add_argument("--out", required=True)
    c.set_defaults(fn=cmd_cost)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
