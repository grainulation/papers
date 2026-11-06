#!/usr/bin/env python3
"""Local-corpus capture: `bran-capture/1` records for sealed corpus passages.

Spec: v3/SWARM3_DESIGN.md §2.4 and v3/evidence-corpus-addendum.md, as a
delta to v2/evidence-verification-spec.md §1.

A corpus passage is "captured" by reading its text from the sealed corpus
(L1, tools/corpus/). Nothing is fetched: this module never opens a socket,
never resolves a name and never reads robots.txt. The record has the same
schema as a web capture, with identifier_kind "corpus":

    requested = request_url = resolved_url = canonical_url
              = corpus://<corpus_id>/<pct-encoded passage_key>
    redirects [] · http_status null · content_type text/plain
    content_sha256 = SHA-256 of the passage's UTF-8 bytes
    extraction.method corpus/1 · robots {checked: false, allowed: null, robots_sha256: null}
    license_note from the corpus manifest
    outcome ok (sanitized text non-empty; ok_rule corpus-nonempty/1) | ok_no_text (empty)
            | invalid_identifier (key not in corpus)

capture_tool_version pins the corpus: it embeds corpus_sha256, so a new
corpus gives new capture ids.

Records go into the same content-addressed cache as web captures
(capture.Cache: blobs/, text/, captures/, index/), so
`capture.py verify-cache` and `support/check.py` read them unchanged.

Stdlib only. Run with `python3 -I`.
"""

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import canonical  # noqa: E402
import capture  # noqa: E402
from canonical import canonical_bytes, canonical_json, record_id, sha256_hex  # noqa: E402

FORMAT = capture.FORMAT  # "bran-capture/1"
SEMVER = "0.1.0"
KIND = "corpus"
SCHEME = "corpus://"
EXTRACTION_METHOD = "corpus/1"
MANIFEST_FORMAT = "bran-corpus-manifest/1"
DEFAULT_EPOCH = "corpus"
DEFAULT_MANIFEST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus", "corpus_manifest.json")
MAX_KEY_CHARS = 1024

CORPUS_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
# percent-encoded passage key: RFC 3986 unreserved + ":" verbatim, all
# else %XX with uppercase hex (exactly urllib.parse.quote(key, safe=":")).
_ENC_KEY = re.compile(r"^(?:[A-Za-z0-9\-._~:]|%[0-9A-F]{2})+$")
_VERBATIM = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~:")

DEFAULT_CONFIG = {
    # When a found passage is `ok`. The web 200-char threshold (spec §1.3)
    # does not apply: a passage is the sealed unit of evidence by
    # construction (integrator decision, addendum §1.2). Pinned through
    # the config hash in capture_tool_version.
    "ok_rule": "corpus-nonempty/1",
    "max_text_chars": 200_000,
    "extraction": EXTRACTION_METHOD,
    "url_encoding": "pct-quote-safe-colon/1",
}


class CorpusError(ValueError):
    pass


# ── identifiers ──

def corpus_url(corpus_id, passage_key):
    """corpus://<corpus_id>/<passage_key percent-encoded>. Bijective: see parse_corpus_url."""
    if not CORPUS_ID.match(corpus_id or ""):
        raise CorpusError("bad corpus_id %r" % (corpus_id,))
    if not isinstance(passage_key, str) or not passage_key or len(passage_key) > MAX_KEY_CHARS:
        raise CorpusError("bad passage_key %r" % (passage_key,))
    return SCHEME + corpus_id + "/" + urllib.parse.quote(passage_key, safe=":")


def parse_corpus_url(url):
    """(corpus_id, passage_key) for a canonical corpus URL, else None.
    Non-canonical encodings (lowercase hex, %XX of a verbatim char) are
    rejected so each passage has exactly one URL."""
    if not isinstance(url, str) or not url.startswith(SCHEME):
        return None
    rest = url[len(SCHEME):]
    cid, sep, enc = rest.partition("/")
    if not sep or not CORPUS_ID.match(cid) or not _ENC_KEY.match(enc):
        return None
    for m in re.finditer(r"%([0-9A-F]{2})", enc):
        if chr(int(m.group(1), 16)) in _VERBATIM:
            return None
    try:
        key = urllib.parse.unquote(enc, errors="strict")
    except UnicodeDecodeError:
        return None
    if len(key) > MAX_KEY_CHARS or urllib.parse.quote(key, safe=":") != enc:
        return None
    return cid, key


def xref_key(url):
    """Cross-reference key the reducer derives (bran/src/evidence.rs): corpus:<corpus_id>/<encoded key>."""
    return "corpus:" + url[len(SCHEME):]


# ── the corpus (adapter over L1's tools/corpus/ output; addendum §2) ──

def _open_text(path):
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, encoding="utf-8")


def passage_content(title, text):
    """L1's build.passage_content: the indexed, displayed and hashed string."""
    return "%s\n%s" % (title, text)


class CorpusSource:
    """Read-only view of one sealed corpus: identity from L1's
    `bran-corpus-manifest/1` (corpora.<id>.{corpus_sha256, license,
    passages.file, passages.passages_sha256}), passage content from its
    `passages.jsonl` (lines {key, title, text, ...}; content =
    title + "\n" + text). Only this class knows L1's layout."""

    def __init__(self, corpus_id, corpus_sha256, license_note, passages_path=None, passages=None,
                 passages_sha256=None):
        if not CORPUS_ID.match(corpus_id or ""):
            raise CorpusError("bad corpus_id %r" % (corpus_id,))
        if not HEX64.match(corpus_sha256 or ""):
            raise CorpusError("corpus_sha256 must be 64 lowercase hex chars")
        self.corpus_id = corpus_id
        self.corpus_sha256 = corpus_sha256
        self.license_note = license_note
        self.passages_path = passages_path
        self.passages_sha256 = passages_sha256
        self._mem = dict(passages) if passages is not None else None

    @classmethod
    def from_manifest(cls, manifest_path, corpus_id, repo_root=None):
        """repo_root: base of the manifest's repo-relative paths; default is
        the manifest's grandparent directory (tools/corpus/ -> repo)."""
        with open(manifest_path, encoding="utf-8") as fh:
            m = json.load(fh)
        if m.get("format") != MANIFEST_FORMAT:
            raise CorpusError("manifest format %r (expected %s)" % (m.get("format"), MANIFEST_FORMAT))
        e = (m.get("corpora") or {}).get(corpus_id)
        if e is None:
            raise CorpusError("corpus %r not in manifest (has %s)" % (corpus_id, sorted(m.get("corpora") or {})))
        pas = e.get("passages") or {}
        if not pas.get("file"):
            raise CorpusError("corpus %r has no passages file (not built yet?)" % corpus_id)
        root = repo_root or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(manifest_path))))
        path = pas["file"] if os.path.isabs(pas["file"]) else os.path.join(root, pas["file"])
        return cls(corpus_id, e.get("corpus_sha256"), e.get("license"), passages_path=path,
                   passages_sha256=pas.get("passages_sha256"))

    def verify_passages(self):
        """Recompute the passages file hash against the manifest (slow on FEVER)."""
        if self.passages_sha256 is None:
            raise CorpusError("manifest has no passages_sha256")
        h = hashlib.sha256()
        with open(self.passages_path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 22), b""):
                h.update(block)
        if h.hexdigest() != self.passages_sha256:
            raise CorpusError("passages file %s does not match the manifest" % self.passages_path)

    def lookup(self, keys):
        """{key: content} for the keys present (one pass over the file)."""
        want = set(keys)
        if self._mem is not None:
            return {k: self._mem[k] for k in want if k in self._mem}
        found = {}
        with _open_text(self.passages_path) as fh:
            for n, line in enumerate(fh, 1):
                if not want:
                    break
                if not line.strip():
                    continue
                d = json.loads(line)
                k = d.get("key")
                if k in want:
                    if not isinstance(d.get("text"), str) or not isinstance(d.get("title"), str):
                        raise CorpusError("passage %r (line %d) lacks title/text" % (k, n))
                    found[k] = passage_content(d["title"], d["text"])
                    want.discard(k)
        return found


# ── records ──

def _blob12(path):
    with open(path, "rb") as fh:
        return canonical.git_blob_sha1(fh.read())[:12]


def make_config(**over):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    for k, v in over.items():
        if k not in cfg:
            raise KeyError(k)
        cfg[k] = v
    if cfg["ok_rule"] not in OK_RULES:
        raise CorpusError("unknown ok_rule %r" % (cfg["ok_rule"],))
    canonical_json(cfg)  # no floats
    return cfg


def tool_version(cfg, corpus_sha256):
    """0.1.0+<corpus_capture.py>.<capture.py>.<canonical.py>.c<corpus_sha256>.k<config>.
    capture.py is included because its sanitize_text shapes text_sha256."""
    here = os.path.dirname(os.path.abspath(__file__))
    cfgh = canonical.sha256_hex16(canonical_bytes(cfg))[:12]
    return "%s+%s.%s.%s.c%s.k%s" % (
        SEMVER, _blob12(os.path.join(here, "corpus_capture.py")), _blob12(os.path.join(here, "capture.py")),
        _blob12(os.path.join(here, "canonical.py")), corpus_sha256, cfgh)


OK_RULES = {"corpus-nonempty/1": lambda txt: len(txt) > 0}


def _is_ok(txt, cfg):
    try:
        return OK_RULES[cfg["ok_rule"]](txt)
    except KeyError:
        raise CorpusError("unknown ok_rule %r" % (cfg.get("ok_rule"),))


def build_record(corpus_id, passage_key, text, license_note, version, cfg=None):
    """Sealed record for one passage (text None = key not in the corpus).
    Returns (record, body_bytes|None, sanitized_text|None). Pure."""
    cfg = cfg or make_config()
    url = corpus_url(corpus_id, passage_key)
    rec = {
        "format": FORMAT,
        "requested": url,
        "identifier_kind": KIND,
        "request_url": url,
        "redirects": [],
        "resolved_url": None,
        "canonical_url": None,
        "http_status": None,
        "content_type": None,
        "content_length": 0,
        "truncated": False,
        "content_sha256": None,
        "extraction": None,
        "outcome": "invalid_identifier",
        "robots": {"checked": False, "allowed": None, "robots_sha256": None},
        "license_note": None,
        "capture_tool_version": version,
    }
    if text is None:
        return rec, None, None
    body = text.encode("utf-8")
    txt = capture.sanitize_text(text, cfg["max_text_chars"])
    rec.update({
        "resolved_url": url,
        "canonical_url": url,
        "content_type": "text/plain",
        "content_length": len(body),
        "content_sha256": sha256_hex(body),
        "extraction": {"method": EXTRACTION_METHOD, "method_version": "1",
                       "text_sha256": sha256_hex(txt.encode("utf-8")), "text_chars": len(txt)},
        "outcome": "ok" if _is_ok(txt, cfg) else "ok_no_text",
        "license_note": license_note,
    })
    canonical_json(rec)
    return rec, body, txt


def _index_map(cache, epoch):
    """{request_url: capture_id} for one epoch; first entry wins (as capture.Cache.lookup)."""
    ip = os.path.join(cache.root, "index", "captures.jsonl")
    out = {}
    if not os.path.exists(ip):
        return out
    with open(ip, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                e = json.loads(line)
                if e["epoch"] == epoch:
                    out.setdefault(e["request_url"], e["capture_id"])
    return out


def capture_passages(keys, source, cache, epoch=DEFAULT_EPOCH, offline=False, cfg=None):
    """Capture each passage key once. Returns [(passage_key, capture_id, record)].
    Offline reads only index/ + captures/; any miss raises capture.CacheMiss
    before anything is written. Online never touches the network either:
    it reads the corpus file."""
    cfg = cfg or make_config()
    uniq = list(dict.fromkeys(keys))
    urls = {k: corpus_url(source.corpus_id, k) for k in uniq}
    idx = _index_map(cache, epoch)
    if offline:
        out = []
        for k in uniq:
            cid = idx.get(urls[k])
            if cid is None:
                raise capture.CacheMiss("%s (epoch %s)" % (urls[k], epoch))
            out.append((k, cid, cache.load(cid)[0]))
        return out
    version = tool_version(cfg, source.corpus_sha256)
    missing = [k for k in uniq if urls[k] not in idx]
    texts = source.lookup(missing) if missing else {}
    out = []
    for k in uniq:
        cid = idx.get(urls[k])
        if cid is not None:
            rec = cache.load(cid)[0]
        else:
            rec, body, txt = build_record(source.corpus_id, k, texts.get(k), source.license_note, version, cfg)
            tel = {"source": "corpus", "corpus_id": source.corpus_id, "found": k in texts}
            cid = cache.put(epoch, rec, tel, body, txt)
            idx[urls[k]] = cid
        out.append((k, cid, rec))
    return out


# ── agent citations → passage keys (bran-retrieval/1, design §2.3, §3.3) ──

_PLABEL = re.compile(r"^P([1-9][0-9]*)$")


def citation_keys(retrieval, citations, corpus_id=None):
    """Map an agent's citation labels (P1..Pk) to passage keys through the
    item's bran-retrieval/1 record. A label outside 1..k (or not of the
    form P<n>) maps to itself, which is not a corpus key, so it is
    captured as invalid_identifier (design §2.4 item 4)."""
    if corpus_id is not None and retrieval.get("corpus_id") != corpus_id:
        raise CorpusError("retrieval corpus_id %r != %r" % (retrieval.get("corpus_id"), corpus_id))
    results = retrieval.get("results") or []
    out = []
    for lab in citations:
        m = _PLABEL.match(lab)
        i = int(m.group(1)) if m else 0
        out.append(results[i - 1]["passage_key"] if 1 <= i <= len(results) else lab)
    return out


# ── CLI ──

def _read_keys(args):
    keys = list(args.key or [])
    if args.keys:
        with open(args.keys, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("{"):
                    d = json.loads(line)
                    keys.append(d.get("passage_key", d.get("key")))
                else:
                    keys.append(line)
    return keys


def _source(args):
    src = CorpusSource.from_manifest(args.manifest, args.corpus, repo_root=args.repo_root)
    if getattr(args, "verify_passages", False):
        src.verify_passages()
    return src


def cmd_capture(args):
    src = _source(args)
    cache = capture.Cache(args.cache)
    try:
        res = capture_passages(_read_keys(args), src, cache, epoch=args.epoch, offline=args.offline)
    except capture.CacheMiss as e:
        print("cache miss (offline): %s" % e, file=sys.stderr)
        return 3
    except capture.CacheCorrupt as e:
        print("cache corrupt: %s" % e, file=sys.stderr)
        return 4
    dist, lines = {}, []
    for k, cid, rec in res:
        dist[rec["outcome"]] = dist.get(rec["outcome"], 0) + 1
        lines.append(canonical_json({"kind": KIND, "passage_key": k, "requested": rec["requested"],
                                     "capture_id": cid, "outcome": rec["outcome"]}))
    data = "\n".join(lines) + ("\n" if lines else "")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(data)
    else:
        sys.stdout.write(data)
    print(json.dumps({"captured": len(res), "outcomes": dict(sorted(dist.items()))}), file=sys.stderr)
    return 0


def cmd_version(args):
    print(tool_version(make_config(), _source(args).corpus_sha256))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="bran-capture/1 records for local corpus passages (no network)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("capture")
    p.add_argument("--manifest", default=DEFAULT_MANIFEST, help="L1 corpus_manifest.json")
    p.add_argument("--corpus", required=True, help="corpus_id in the manifest (fever17, scifact)")
    p.add_argument("--repo-root", help="base of the manifest's relative paths (default: manifest/../..)")
    p.add_argument("--verify-passages", action="store_true", help="re-hash passages.jsonl against the manifest first")
    p.add_argument("--keys", help="file: one passage_key per line, or JSONL with passage_key")
    p.add_argument("--key", action="append", help="single passage key (repeatable)")
    p.add_argument("--cache", required=True)
    p.add_argument("--epoch", default=DEFAULT_EPOCH)
    p.add_argument("--offline", action="store_true", help="read only the cache; a miss exits 3 and writes nothing")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_capture)
    p = sub.add_parser("version")
    p.add_argument("--manifest", default=DEFAULT_MANIFEST)
    p.add_argument("--corpus", required=True)
    p.add_argument("--repo-root")
    p.set_defaults(fn=cmd_version)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
