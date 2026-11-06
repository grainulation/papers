#!/usr/bin/env python3
"""Support checker: bm25/1 span selection + headless Claude CLI judge -> bran-support/1.

Spec: v2/evidence-verification-spec.md §2 (bran-support/1), §5.3-§5.4, §6 L4c.
Deviations from the spec (Ollama -> Claude Code CLI) are listed in README.md.

Safety properties:
  * Fetched text and the claim are passed only as delimited data inside a
    fixed prompt template (prompt_template.txt, sha256 sealed). Any run of
    three or more angle-bracket-like characters inside either is replaced
    before insertion, so the text cannot close a delimiter.
  * The prompt goes to the CLI on stdin; argv is a fixed list (no shell),
    so fetched text is never interpolated into a command line.
  * The CLI runs with all tools disabled (--tools ""), no MCP servers
    (--strict-mcp-config, no --mcp-config), --safe-mode (no CLAUDE.md,
    skills, plugins, hooks), no setting sources, no slash commands, no
    session persistence, a per-call budget cap, and an empty working
    directory. The only tool the model sees is the CLI's built-in
    StructuredOutput tool bound to RESPONSE_SCHEMA.
  * Output parsing is strict: exactly {label, confidence}, label in the
    enum, confidence an integer 0..10000; anything else -> parse_error.
  * The model id the CLI reports must equal the pin, else model_mismatch.

Model outputs are cached by check_key = sha256_hex16(checker_id, rendered
prompt) — i.e. by (claim text, span texts, checker) — so nothing is
re-queried. Re-checking (force=True) is regeneration (spec §4).

Stdlib only. Run with `python3 -I`.
"""

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # tools/evidence (L4b's canonical.py)
from canonical import canonical_bytes, canonical_json, record_id, sha256_hex, sha256_hex16, git_blob_sha1  # noqa: E402

FORMAT = "bran-support/1"
SEMVER = "0.2.0"  # 0.2.0: prompt v2 (silence -> not_enough_info), CLI version bound into the id
TEMPLATE_PATH = os.path.join(HERE, "prompt_template.txt")
PIN_PATH = os.path.join(HERE, "pin.json")
# Prefer the public name; the fallback reads historical launch configurations.
DEFAULT_CLAUDE = os.environ.get("OVERTURN_CLAUDE_BIN", os.environ.get("BRAN_CLAUDE_BIN", "claude"))

LABELS = ("supports", "refutes", "not_enough_info")
STATUSES = ("ok", "parse_error", "timeout", "input_too_long", "model_mismatch", "refused", "checker_error")
# statuses whose model output is cached (deterministic given the inputs, or a
# genuine model answer); timeout / checker_error are transient and retried.
# refused: the hosted model's safeguards declined the input (stop_reason
# "refusal"); stable for a given input, so sealed with a null label.
CACHEABLE = ("ok", "parse_error", "model_mismatch", "input_too_long", "refused")

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": list(LABELS)},
        "confidence": {"type": "integer", "minimum": 0, "maximum": 10000},
    },
    "required": ["label", "confidence"],
    "additionalProperties": False,
}
RESPONSE_SCHEMA_JSON = json.dumps(RESPONSE_SCHEMA, sort_keys=True, separators=(",", ":"))

# bm25/1 parameters (integers only, spec §2.1)
BM25_PARAMS = {"k1_x1000": 1200, "b_x1000": 750, "chunk_chars": 1000, "overlap_chars": 200}
SPAN_SELECTOR_VERSION = "1"
MAX_SPANS = 3
MAX_CLAIM_CHARS = 2000
MAX_PROMPT_CHARS = 6000

# ── bm25/1 span selection ──

_TOKEN = re.compile(r"\w+", re.UNICODE)
STOPWORDS = frozenset(
    "a an and are as at be been but by can do does for from had has have how if in into is it its "
    "may more most no not of on or such than that the their then there these they this those to "
    "was were what when where which while who will with would".split())


def tokenize(s):
    return [t for t in _TOKEN.findall(unicodedata.normalize("NFC", s).casefold()) if t not in STOPWORDS]


def chunk_offsets(n, chunk_chars, overlap_chars):
    """[(start, end)] covering [0, n): fixed windows, stride chunk-overlap."""
    if n <= chunk_chars:
        return [(0, n)]
    stride = chunk_chars - overlap_chars
    out, s = [], 0
    while True:
        e = min(s + chunk_chars, n)
        out.append((s, e))
        if e >= n:
            break
        s += stride
    return out


def bm25_scores(query_tokens, docs_tokens, k1, b):
    n = len(docs_tokens)
    avgdl = (sum(len(d) for d in docs_tokens) / n) if n else 0.0
    df = {}
    for d in docs_tokens:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    q = sorted(set(query_tokens))  # fixed summation order
    scores = []
    for d in docs_tokens:
        tf = {}
        for t in d:
            tf[t] = tf.get(t, 0) + 1
        s = 0.0
        dl = len(d)
        for t in q:
            f = tf.get(t, 0)
            if not f:
                continue
            idf = math.log(1.0 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * f * (k1 + 1.0) / (f + k1 * (1.0 - b + b * dl / (avgdl or 1.0)))
        scores.append(s)
    return scores


def select_spans(text, query, params=BM25_PARAMS, max_spans=MAX_SPANS):
    """Deterministic: chunk, score with BM25 against the claim, take the top
    max_spans non-overlapping chunks (ties -> lower start offset), return
    them in offset order. If no chunk shares a term, the first chunk.
    Offsets are Python str indices = Unicode scalar indices."""
    if not text:
        return []
    n, cc = len(text), params["chunk_chars"]
    if n <= max_spans * cc:
        # the whole text fits in the span budget: partition it into
        # ceil(n/cc) equal non-overlapping spans (no ranking needed)
        k = -(-n // cc)
        cuts = [n * i // k for i in range(k + 1)]
        return [(cuts[i], cuts[i + 1]) for i in range(k)]
    offs = chunk_offsets(n, cc, params["overlap_chars"])
    docs = [tokenize(text[s:e]) for s, e in offs]
    scores = bm25_scores(tokenize(query), docs, params["k1_x1000"] / 1000.0, params["b_x1000"] / 1000.0)
    # quantize so platform float noise cannot reorder near-ties
    ranked = sorted(range(len(offs)), key=lambda i: (-round(scores[i] * 1e6), offs[i][0]))
    chosen = []
    for i in ranked:
        if len(chosen) >= max_spans or round(scores[i] * 1e6) <= 0:
            break
        s, e = offs[i]
        if any(s < ce and cs < e for cs, ce in chosen):
            continue
        chosen.append((s, e))
    if not chosen:
        chosen = [offs[0]]
    return sorted(chosen)


# ── prompt construction (§5.4) ──

_DELIM = re.compile(r"[<>＜＞‹›«»〈〉〈〉❬-❱⟨⟩﹤﹥]{3,}")


def neutralize(s):
    """Remove anything that could open or close a fixed delimiter."""
    s = unicodedata.normalize("NFC", s)
    s = "".join(ch for ch in s if ch in "\n\t" or unicodedata.category(ch) != "Cc")
    return _DELIM.sub("[x]", s)  # 3 chars: never longer than the >=3-char run it replaces


def span_text(text, s, e):
    """Sealed span text: neutralized, capped at the 1,000-char limit the Rust
    validator enforces (neutralize never lengthens NFC input; the cap is a guard)."""
    return neutralize(text[s:e])[:BM25_PARAMS["chunk_chars"]]


def load_template(path=TEMPLATE_PATH):
    with open(path, "rb") as fh:
        raw = fh.read()
    txt = raw.decode("utf-8")
    m = re.match(r"=== SYSTEM ===\n(.*?)\n=== USER ===\n(.*)\Z", txt, re.S)
    if not m:
        raise ValueError("prompt template must have === SYSTEM === and === USER === sections")
    user = m.group(2)
    if user.count("{claim}") != 1 or user.count("{passage}") != 1:
        raise ValueError("template must contain {claim} and {passage} exactly once")
    return {"system": m.group(1), "user": user, "sha256": sha256_hex(raw)}


def claim_text(claim):
    raw = (claim.get("raw_text") or "").strip()
    if raw:
        return raw
    neg = str(claim.get("polarity", "")).upper() == "NEGATE"
    parts = [claim.get("subject") or "", ("not " if neg else "") + (claim.get("predicate") or ""), claim.get("object") or ""]
    return " ".join(p.strip() for p in parts if p and p.strip())


def render_user(template, claim_str, span_texts):
    passage = "\n[...]\n".join(span_texts)
    vals = {"claim": neutralize(claim_str), "passage": passage}
    # single pass: substituted values are never re-scanned for placeholders
    return re.sub(r"\{(claim|passage)\}", lambda m: vals[m.group(1)], template["user"])


# ── checker identity ──

def load_pin(path=PIN_PATH):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def cli_flags(pin, template):
    """argv after the binary. The system prompt is the template's SYSTEM
    section; in the sealed record it is shown as a reference to the
    template hash to keep records small."""
    return [
        "-p",
        "--model", pin["model"],
        "--output-format", "json",
        "--json-schema", RESPONSE_SCHEMA_JSON,
        "--tools", "",
        "--strict-mcp-config",
        "--safe-mode",
        "--setting-sources", "",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--effort", pin["effort"],
        "--max-budget-usd", pin["max_budget_usd"],
        "--system-prompt", "@prompt_template.txt#SYSTEM",
    ]


def tool_version():
    blobs = []
    for name in ("check.py", "prompt_template.txt"):
        with open(os.path.join(HERE, name), "rb") as fh:
            blobs.append(git_blob_sha1(fh.read())[:12])
    return "%s+%s.%s" % (SEMVER, blobs[0], blobs[1])


_version_cache = {}


def cli_version(claude_bin):
    if claude_bin not in _version_cache:
        try:
            out = subprocess.run([claude_bin, "--version"], capture_output=True, text=True, timeout=30,
                                 stdin=subprocess.DEVNULL).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        m = re.search(r"\d+\.\d+\.\d+", out)
        _version_cache[claude_bin] = m.group(0) if m else None
    return _version_cache[claude_bin]


# Values for the Ollama-shaped Rust `Checker` struct (bran/src/evidence.rs)
# that have no meaning for a hosted model behind the CLI:
HOSTED_MODEL_DIGEST = "hosted:none"      # no weights digest exists
DECODING_NOT_SETTABLE = -1               # the CLI exposes no sampling controls
DECODING = {k: DECODING_NOT_SETTABLE for k in ("temperature_x1000", "top_k", "top_p_x1000", "num_ctx", "num_predict", "seed")}


def flags_sha256(pin, flags):
    """Binds backend, argv flags and response schema into checker_tool_version
    (and so into checker_id), like L4b's config hash in capture_tool_version."""
    return sha256_hex(canonical_bytes({"backend": pin["backend"], "flags": flags,
                                       "response_schema": RESPONSE_SCHEMA_JSON}))


def compute_checker_id(block):
    """Same formula as Rust Checker::compute_id (bran/src/evidence.rs)."""
    return sha256_hex16(canonical_bytes({k: block[k] for k in (
        "model", "model_digest", "prompt_template_sha256", "decoding", "checker_tool_version")}))


class Checker:
    def __init__(self, claude_bin=DEFAULT_CLAUDE, pin=None, template=None, workdir=None, checker_tool_version=None):
        self.claude_bin = claude_bin
        self.pin = pin or load_pin()
        self.template = template or load_template()
        self.flags = cli_flags(self.pin, self.template)
        self.workdir = workdir or tempfile.mkdtemp(prefix="bran-support-")
        self.flags_sha256 = flags_sha256(self.pin, self.flags)
        # The Claude Code CLI wraps the model (its own system prompt, tool
        # plumbing, structured-output handling), so its version is part of the
        # checker: bound into checker_tool_version, hence into checker_id. A CLI
        # upgrade yields a new checker_id at the next process start.
        self.cli_version = cli_version(self.claude_bin) or "unknown"
        self.tool_version = checker_tool_version or (
            tool_version() + ".f" + self.flags_sha256[:12] + ".cli" + self.cli_version)
        self.ident = {
            "model": self.pin["model"],
            "model_digest": self.pin.get("model_digest") or HOSTED_MODEL_DIGEST,
            "prompt_template_sha256": self.template["sha256"],
            "decoding": dict(DECODING),
            "checker_tool_version": self.tool_version,
        }
        self.checker_id = compute_checker_id(self.ident)

    def checker_block(self, model_reported=None):
        """Exactly the Rust `Checker` fields (deny_unknown_fields). The
        CLI version goes in `ollama_version` too (since 0.2.0 it is also in
        checker_tool_version, so in the id).
        The reported model is not a field: a mismatch is status model_mismatch."""
        b = dict(self.ident)
        b["checker_id"] = self.checker_id
        b["ollama_version"] = "claude-code/%s" % self.cli_version
        return b

    def describe(self):
        """Full identity for reports (not sealed in records)."""
        return dict(self.checker_block(), backend=self.pin["backend"], cli_version=self.cli_version, flags=self.flags,
                    flags_sha256=self.flags_sha256,
                    response_schema_sha256=sha256_hex(RESPONSE_SCHEMA_JSON.encode()))

    def _argv(self):
        argv = [self.claude_bin] + list(self.flags)
        argv[-1] = self.template["system"]
        return argv

    def call(self, user_prompt):
        """-> dict(status, label, score_q, model_output, model_reported, transcript, duration_ms, cost_usd)"""
        t0 = time.monotonic()
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_SSE") and k != "CLAUDECODE"}
        try:
            cp = subprocess.run(self._argv(), input=user_prompt.encode("utf-8"), capture_output=True,
                                timeout=int(self.pin.get("timeout_s", 120)), cwd=self.workdir, env=env)
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "duration_ms": int((time.monotonic() - t0) * 1000)}
        except OSError as e:
            return {"status": "checker_error", "error": str(e), "duration_ms": 0}
        res = parse_cli_output(cp.stdout, self.pin["model"])
        res["duration_ms"] = int((time.monotonic() - t0) * 1000)
        res["exit_code"] = cp.returncode
        res["transcript"] = cp.stdout.decode("utf-8", "replace")
        if cp.returncode != 0 and res["status"] == "ok":
            res["status"] = "checker_error"
        if res["status"] == "checker_error":
            res["stderr"] = cp.stderr.decode("utf-8", "replace")[-2000:]
        return res


def parse_cli_output(stdout_bytes, pinned_model):
    """Strict parse of `claude -p --output-format json`. Accepts a single
    result object or the event array. Never raises."""
    out = {"status": "parse_error", "label": None, "score_q": None, "model_output": None,
           "model_reported": None, "cost_usd": None}
    try:
        doc = json.loads(stdout_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        out["status"] = "checker_error"
        return out
    events = doc if isinstance(doc, list) else [doc]
    result = None
    models = []
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
        out["status"] = "checker_error"
        return out
    out["cost_usd"] = result.get("total_cost_usd")
    if not models and isinstance(result.get("modelUsage"), dict):
        models = sorted(result["modelUsage"].keys())
    out["model_reported"] = ",".join(models) if models else None
    if result.get("stop_reason") == "refusal":
        out["status"] = "refused"
        mo = result.get("result")
        # keep only the stable part of the refusal text (request ids vary)
        out["model_output"] = "refusal:" + (mo.split("\n", 1)[0][:200] if isinstance(mo, str) else "")
        return out
    if result.get("is_error") or result.get("subtype") != "success":
        out["status"] = "checker_error"
        return out
    model_output = result.get("result")
    out["model_output"] = model_output if isinstance(model_output, str) else None
    if models != [pinned_model]:
        out["status"] = "model_mismatch"
        return out
    so = result.get("structured_output")
    if so is None and isinstance(model_output, str):
        try:
            so = json.loads(model_output)
        except ValueError:
            so = None
    if not isinstance(so, dict) or set(so.keys()) != {"label", "confidence"}:
        return out
    lab, conf = so["label"], so["confidence"]
    if lab not in LABELS or isinstance(conf, bool) or not isinstance(conf, int) or not 0 <= conf <= 10000:
        return out
    out.update(status="ok", label=lab, score_q=conf,
               model_output=canonical_json({"confidence": conf, "label": lab}))
    return out


# ── support cache (spec §1.5 layout; L4b owns captures/ and text/) ──

class SupportCache:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self._lock = threading.Lock()
        self._checks = None

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

    def _append(self, rel, obj):
        p = self._p("index", rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(canonical_json(obj) + "\n")

    def checks(self):
        if self._checks is None:
            self._checks = {}
            p = self._p("index", "support_checks.jsonl")
            if os.path.exists(p):
                with open(p, encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            e = json.loads(line)
                            self._checks.setdefault(e["check_key"], e)  # first is authoritative
        return self._checks

    def get_check(self, key):
        with self._lock:
            return self.checks().get(key)

    def put_check(self, key, res):
        raw = (res.get("model_output") or "").encode("utf-8")
        r = sha256_hex(raw)
        with self._lock:
            self._write_once(self._p("support", "raw", r[:2], r + ".txt"), raw)
            e = {"check_key": key, "status": res["status"], "label": res.get("label"),
                 "score_q": res.get("score_q"), "raw_output_sha256": r,
                 "model_reported": res.get("model_reported")}
            if key not in self.checks():
                self.checks()[key] = e
                self._append("support_checks.jsonl", e)
            return self.checks()[key]

    def put_record(self, rec, telemetry, evidence_index=None):
        sid = record_id(rec)
        with self._lock:
            self._write_once(self._p("support", sid + ".json"), canonical_bytes(rec))
            tp = self._p("support", sid + ".telemetry.json")
            hist = []
            if os.path.exists(tp):
                with open(tp, encoding="utf-8") as fh:
                    hist = json.load(fh)
            hist.append(telemetry)
            with open(tp, "w", encoding="utf-8") as fh:
                json.dump(hist, fh, indent=1, sort_keys=True)
            self._append("support.jsonl", {"contribution_id": rec["contribution_id"],
                                           "evidence_index": evidence_index, "support_id": sid})
        return sid


# ── capture cache reading (format of L4b's tools/evidence/capture.py, spec §1.5) ──

class CaptureError(RuntimeError):
    pass


def load_capture(cache_root, capture_id):
    p = os.path.join(cache_root, "captures", capture_id + ".json")
    if not os.path.exists(p):
        raise CaptureError("capture %s not in cache" % capture_id)
    with open(p, "rb") as fh:
        data = fh.read()
    rec = json.loads(data)
    if record_id(rec) != capture_id or canonical_bytes(rec) != data:
        raise CaptureError("capture %s does not hash to its id" % capture_id)
    return rec


def load_capture_text(cache_root, rec):
    ex = rec.get("extraction")
    if not ex:
        raise CaptureError("capture has no extraction")
    t = ex["text_sha256"]
    p = os.path.join(cache_root, "text", "sha256", t[:2], t + ".txt")
    with open(p, "rb") as fh:
        raw = fh.read()
    if sha256_hex(raw) != t:
        raise CaptureError("text %s hash mismatch" % t)
    return raw.decode("utf-8")


# ── the check ──

def normalize_claim(c):
    """Copied verbatim from the contribution: the Rust validator requires it
    to equal SupportClaim::of(canonical_form, raw_text) (polarity AFFIRM|NEGATE)."""
    return {k: c[k] for k in ("subject", "predicate", "object", "polarity", "raw_text")}


def check_text(checker, cache, claim, text, force=False):
    """Run (or reuse) one check of claim against extracted text.
    Returns (spans, check_entry, call_result_or_None)."""
    cstr = claim_text(claim)
    query = " ".join([cstr, claim.get("subject") or "", claim.get("object") or ""])
    offs = select_spans(text, query)
    spans = [{"start": s, "end": e, "text": span_text(text, s, e)} for s, e in offs]
    user = render_user(checker.template, cstr, [sp["text"] for sp in spans])
    key = sha256_hex16(canonical_bytes({"checker_id": checker.checker_id, "prompt_sha256": sha256_hex(user.encode("utf-8"))}))
    if len(cstr) > MAX_CLAIM_CHARS or len(user) > MAX_PROMPT_CHARS or not cstr:
        res = {"status": "input_too_long", "label": None, "score_q": None, "model_output": None, "model_reported": None}
        return spans, key, (cache.put_check(key, res) if cache else _entry(key, res)), None
    if cache and not force:
        hit = cache.get_check(key)
        if hit:
            return spans, key, hit, None
    res = checker.call(user)
    if cache and not force and res["status"] in CACHEABLE:
        entry = cache.put_check(key, res)
    else:
        # transient failure, or regeneration (force): the first cached answer
        # stays authoritative; the fresh answer is returned, not cached.
        entry = _entry(key, res)
    return spans, key, entry, res


def _entry(key, res):
    return {"check_key": key, "status": res["status"], "label": res.get("label"), "score_q": res.get("score_q"),
            "raw_output_sha256": sha256_hex((res.get("model_output") or "").encode("utf-8")),
            "model_reported": res.get("model_reported")}


# Rust SupportStatus has no `refused`; a safeguard refusal is sealed as
# parse_error (no label, scored unchecked). The refusal stays visible in the
# raw output, whose hash is sealed.
RECORD_STATUS = {"refused": "parse_error"}


def build_record(checker, contribution_id, claim, capture_id, spans, entry):
    ok = entry["status"] == "ok"
    return {
        "format": FORMAT,
        "contribution_id": contribution_id,
        "claim": normalize_claim(claim),
        "capture_id": capture_id,
        "spans": spans,
        "span_selector": {"method": "bm25/1", "version": SPAN_SELECTOR_VERSION, "params": dict(BM25_PARAMS)},
        "checker": checker.checker_block(),
        "status": RECORD_STATUS.get(entry["status"], entry["status"]),
        "label": entry["label"] if ok else None,
        "score_q": entry["score_q"] if ok else None,
        "raw_output_sha256": entry["raw_output_sha256"],
    }


def check_contribution(checker, scache, capture_root, item, force=False):
    """item: {contribution_id, claim:{...}, capture_id, evidence_index?}.
    Returns (support_id, record) or (None, reason) when no record is due."""
    rec = load_capture(capture_root, item["capture_id"])
    if rec.get("outcome") != "ok":
        return None, "capture outcome %s: no support record (spec §2)" % rec.get("outcome")
    text = load_capture_text(capture_root, rec)
    spans, key, entry, res = check_text(checker, scache, item["claim"], text, force=force)
    record = build_record(checker, item["contribution_id"], item["claim"], item["capture_id"], spans, entry)
    tel = {"check_key": key, "cached": res is None, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if res is not None:
        tel.update({k: res.get(k) for k in ("duration_ms", "cost_usd", "exit_code")})
    if entry["status"] not in CACHEABLE:
        return None, "transient %s: not sealed, retry later" % entry["status"]
    sid = scache.put_record(record, tel, item.get("evidence_index"))
    return sid, record


def cmd_check(args):
    checker = Checker(claude_bin=args.claude_bin)
    scache = SupportCache(args.support_cache or args.cache)
    n_ok = n_skip = 0
    with open(args.items, encoding="utf-8") as fh:
        items = [json.loads(l) for l in fh if l.strip()]
    for it in items:
        sid, r = check_contribution(checker, scache, args.cache, it, force=args.recheck)
        if sid is None:
            n_skip += 1
            print(json.dumps({"contribution_id": it.get("contribution_id"), "skipped": r}), file=sys.stderr)
            continue
        n_ok += 1
        print(canonical_json({"support_id": sid, "contribution_id": r["contribution_id"], "status": r["status"],
                              "label": r["label"], "score_q": r["score_q"]}))
    print("records=%d skipped=%d checker_id=%s" % (n_ok, n_skip, checker.checker_id), file=sys.stderr)
    return 0


def cmd_id(args):
    c = Checker(claude_bin=args.claude_bin)
    print(json.dumps(c.describe(), indent=1, sort_keys=True))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--claude-bin", default=DEFAULT_CLAUDE)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="check items (JSONL: contribution_id, claim, capture_id, evidence_index)")
    c.add_argument("--items", required=True)
    c.add_argument("--cache", required=True, help="evidence cache root (captures/, text/ from L4b; support/ written here)")
    c.add_argument("--support-cache", help="write support/ and index/support*.jsonl here instead of --cache")
    c.add_argument("--recheck", action="store_true", help="regeneration: query even if cached (first cached answer stays authoritative)")
    c.set_defaults(fn=cmd_check)
    i = sub.add_parser("checker-id", help="print the checker identity block")
    i.set_defaults(fn=cmd_id)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
