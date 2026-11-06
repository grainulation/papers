#!/usr/bin/env python3
"""MiniCheck support checker: bespoke-minicheck:7b (Ollama) behind the same checker interface as
local_check.LocalChecker / check.Checker -> bran-support/1 records. Exploratory (v5 PREREGISTRATION
§2.3, "MiniCheck ... may be validated after collection on the same slices").

What is reused unchanged from check.py (so the model sees the same evidence as 0.2.0):
  * the claim string (check.claim_text of the sealed proposition), neutralize(), bm25/1 spans,
    span_text(), the "\\n[...]\\n" span join (check.render_user), MAX_CLAIM_CHARS / MAX_PROMPT_CHARS,
    check_text() (cache key = (checker_id, rendered prompt)), build_record(), SupportCache.

What differs, and only because MiniCheck was trained on its own input/output format:
  * Prompt template minicheck_template.txt (sha256 sealed as prompt_template_sha256): an empty
    SYSTEM section (no `system` is sent, so the model's own Modelfile defaults apply) and the USER
    section "Document: {passage}\\nClaim: {claim}" -- the format on the Bespoke-MiniCheck-7B model
    card and the Ollama library page. No 0.2.0 rules, delimiters or label definitions are added:
    MiniCheck is a fine-tuned grounding classifier, not an instruction follower.
  * Output: MiniCheck answers "Yes" (the document supports the claim) or "No". No `format`
    (structured output) is sent, since constraining the decoder would change what the model
    emits. Strict parse: done_reason "stop" and the stripped response equal to "Yes" or "No"
    (an optional trailing "." is tolerated); anything else -> parse_error.
  * Label mapping (binary -> the bran-support/1 three-way enum):
        Yes -> supports
        No  -> not_enough_info
    MiniCheck never distinguishes "refutes" from "does not address"; "No" means "not supported".
    not_enough_info is the label whose meaning is exactly "not supported, nothing more claimed".
    Mapping No -> refutes would assert a contradiction the model never judged. Consequences:
    the checker never emits `refutes`; under the gated reducer only `supports` opens the gate, so
    the gate decision is unaffected by this choice, but under an NEI factor > 0 (e.g. nei0.5) a
    "No" passage gets the NEI factor, not 0. See validation/MINICHECK_RESULTS.md.
  * score_q: the probability of the emitted answer token from Ollama logprobs (x10000, rounded),
    when the server returns logprobs; else 10000. It is not used by any frozen policy
    (use_support_score is false), and it is not part of the sealed raw output.

Identity (checker_id, same formula as Rust Checker::compute_id): model, model_digest
("sha256:<manifest digest>", verified against /api/tags), prompt_template_sha256 of
minicheck_template.txt, decoding (all set: temperature 0, seed 42, ...), and checker_tool_version
  <check SEMVER>-minicheck<MC_SEMVER>+<blob minicheck_check.py>.<blob check.py>.<blob template>
  .f<options/endpoint hash>.ollama<server version>.srv<numerics-relevant server config hash>

Stdlib only. Run with `python3 -I`. Pin: minicheck_pin.json.
"""

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import check  # noqa: E402
import local_check as LC  # noqa: E402
from canonical import canonical_bytes, canonical_json, sha256_hex  # noqa: E402

MC_SEMVER = "0.1.0"
MC_PIN_PATH = os.path.join(HERE, "minicheck_pin.json")
MC_TEMPLATE_PATH = os.path.join(HERE, "minicheck_template.txt")
LABEL_MAP = {"Yes": "supports", "No": "not_enough_info"}
_ANSWER = re.compile(r"\A(Yes|No)\.?\Z")


def load_pin(path=MC_PIN_PATH):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def ollama_generate(endpoint, model, prompt, options, keep_alive, timeout, logprobs=True):
    """One non-streaming /api/generate call, no system, no format. -> (data, err, wall_ms)."""
    body = {"model": model, "prompt": prompt, "stream": False, "options": dict(options), "keep_alive": keep_alive}
    if logprobs:
        body.update(logprobs=True, top_logprobs=2)
    t0 = time.monotonic()
    try:
        data = LC.http_json(endpoint, "/api/generate", body, timeout=timeout)
        err = None if isinstance(data.get("response"), str) else "no response field"
    except urllib.error.HTTPError as e:
        data, err = None, "http %s: %s" % (e.code, e.read()[:300].decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        data, err = None, repr(e)
    return data, err, int((time.monotonic() - t0) * 1000)


def answer_prob(data):
    """P(first generated token) from Ollama logprobs, or None."""
    lp = data.get("logprobs")
    if isinstance(lp, list) and lp and isinstance(lp[0], dict) and isinstance(lp[0].get("logprob"), (int, float)):
        return math.exp(lp[0]["logprob"])
    return None


def parse_response(data, pinned_model, options):
    """Strict parse of a MiniCheck /api/generate response. Never raises."""
    out = {"status": "parse_error", "label": None, "score_q": None, "model_output": None, "model_reported": None,
           "cost_usd": 0.0}
    meta = {k: data.get(k) for k in LC.META_KEYS}
    out["meta"] = meta
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
    m = _ANSWER.match(raw.strip())
    if not m:
        return out
    p = answer_prob(data)
    out.update(status="ok", label=LABEL_MAP[m.group(1)],
               score_q=(max(0, min(10000, int(round(p * 10000)))) if p is not None else 10000),
               answer=m.group(1))
    return out


class MiniCheckChecker:
    """Duck-type compatible with check.Checker / local_check.LocalChecker: .template, .checker_id,
    .checker_block(), .describe(), .call(user_prompt)."""

    def __init__(self, pin=None, verify=True, ollama_version=None, server=None, digest=None):
        self.pin = pin or load_pin()
        self.template = check.load_template(MC_TEMPLATE_PATH)
        if self.template["system"].strip():
            raise ValueError("MiniCheck template must have an empty SYSTEM section")
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
        self.model_digest = digest or ("sha256:" + self.pin["model_digest"])
        self.server = server if server is not None else LC.server_config()
        self.flags = {"backend": self.pin["backend"], "endpoint_path": "/api/generate", "stream": False,
                      "options": LC.decoding_block(self.options), "keep_alive": self.pin.get("keep_alive"),
                      "system": None, "format": None, "logprobs": bool(self.pin.get("logprobs", True)),
                      "label_map": LABEL_MAP, "answer_regex": _ANSWER.pattern}
        self.flags_sha256 = sha256_hex(canonical_bytes(self.flags))
        self.server_sha256 = sha256_hex(canonical_bytes(self.server))
        self.tool_version = "%s-minicheck%s+%s.%s.%s.f%s.ollama%s.srv%s" % (
            check.SEMVER, MC_SEMVER, LC._blob(os.path.abspath(__file__)), LC._blob(os.path.join(HERE, "check.py")),
            LC._blob(MC_TEMPLATE_PATH), self.flags_sha256[:12], self.ollama_version, self.server_sha256[:8])
        self.ident = {
            "model": self.pin["model"],
            "model_digest": self.model_digest,
            "prompt_template_sha256": self.template["sha256"],
            "decoding": LC.decoding_block(self.options),
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
                    model_details=self.model_details, label_map=LABEL_MAP)

    def call(self, user_prompt):
        data, err, wall = ollama_generate(self.endpoint, self.pin["model"], user_prompt, self.options,
                                          self.pin.get("keep_alive"), int(self.pin.get("timeout_s", 600)),
                                          logprobs=bool(self.pin.get("logprobs", True)))
        if err is not None:
            st = "timeout" if LC.is_timeout(err) else "checker_error"
            return {"status": st, "error": err, "duration_ms": wall, "cost_usd": 0.0}
        res = parse_response(data, self.pin["model"], self.options)
        res["duration_ms"] = wall
        res["server_ms"] = (data.get("total_duration") or 0) // 1000000
        res["transcript"] = canonical_json(res.pop("meta"))
        return res


def cmd_id(args):
    print(json.dumps(MiniCheckChecker().describe(), indent=1, sort_keys=True))
    return 0


def cmd_check(args):
    checker = MiniCheckChecker()
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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("checker-id").set_defaults(fn=cmd_id)
    c = sub.add_parser("check", help="like check.py check, with the MiniCheck backend")
    c.add_argument("--items", required=True)
    c.add_argument("--cache", required=True)
    c.add_argument("--support-cache")
    c.add_argument("--recheck", action="store_true")
    c.set_defaults(fn=cmd_check)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
