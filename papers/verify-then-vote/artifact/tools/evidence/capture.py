#!/usr/bin/env python3
"""Evidence capture: fetch, content-addressed cache, text extraction, outcome.

Spec: v2/evidence-verification-spec.md §1 (bran-capture/1), §5.2-§5.5, §6 L4b.

Safety properties (each has a unit test in tests/test_capture.py):
  * SSRF: only http/https; every resolved address of every hop (including
    every redirect target) must be globally routable. Loopback (Ollama on
    localhost:11434), RFC 1918, link-local, 169.254.169.254, CGNAT, IPv6
    ULA, IPv4-mapped forms, multicast and reserved ranges are blocked.
    The connection goes to the vetted IP (no second DNS lookup, so no
    rebinding window). Loopback can be opened only for explicitly listed
    test ports, never for 11434, and test mode also refuses every
    non-loopback destination.
  * TLS: ssl.create_default_context() (CERT_REQUIRED, hostname check).
    Verification is never disabled; a corporate CA is added with
    SSL_CERT_FILE or --ca-file.
  * robots.txt is honoured for our user agent on every hop.
  * Limits (§1.4): 5 MiB body (truncate, hash, extract), 200,000 text
    chars, 10 s connect / 30 s total, <= 5 redirects, 1 req/s per host,
    2 retries on transient failures only, no cookies, no auth, no JS.
  * Network gate Q5: a non-test online run requires --network-approved.

Stdlib only. Run with `python3 -I`.
"""

import argparse
import datetime
import gzip
import html.parser
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import sys
import threading
import time
import unicodedata
import urllib.parse
import urllib.robotparser
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import canonical  # noqa: E402
from canonical import canonical_bytes, canonical_json, record_id, sha256_hex  # noqa: E402

FORMAT = "bran-capture/1"
SEMVER = "0.1.0"
UA_TOKEN = "bran-evidence-capture"
OLLAMA_PORT = 11434

OUTCOMES = (
    "ok", "ok_no_text", "not_found", "dns_nxdomain", "invalid_identifier",
    "http_error", "connect_error", "timeout", "tls_error", "too_many_redirects",
    "robots_disallowed", "blocked_ssrf", "blocked_proxy", "unsupported_identifier",
)
OUTCOME_CLASS = {
    "ok": "reachable_text", "ok_no_text": "reachable",
    "not_found": "dead", "dns_nxdomain": "dead", "invalid_identifier": "dead", "blocked_ssrf": "dead",
    "http_error": "transient", "connect_error": "transient", "timeout": "transient",
    "tls_error": "transient", "too_many_redirects": "transient", "robots_disallowed": "transient",
    "blocked_proxy": "transient", "unsupported_identifier": "transient",
}
_TRANSIENT_RETRY = ("connect_error", "timeout", "http_error_5xx")

# Body signatures of corporate TLS-interception / URL-filter block pages.
PROXY_SIGNATURES = (
    r"zscaler",
    r"netskope",
    r"forcepoint|websense",
    r"blue\s?coat|symantec web security",
    r"palo alto networks.{0,200}(url filtering|blocked)",
    r"cisco umbrella|opendns.{0,80}block",
    r"fortiguard|fortinet.{0,120}(blocked|web filter)",
    r"sophos.{0,80}(blocked|web filter)",
    r"(web page|website|this site|access to this (site|page)) (is |has been )?blocked by (your|the) (organization|administrator|network)",
    r"your organization'?s (security )?policy (blocks|does not allow)",
)
PROXY_CA_HINTS = ("zscaler", "netskope", "forcepoint", "bluecoat", "blue coat", "palo alto", "fortinet", "umbrella", "cisco", "gateway ca - cloudflare")

DEFAULT_CONFIG = {
    "max_body_bytes": 5 * 1024 * 1024,
    "max_text_chars": 200_000,
    "min_text_chars": 200,
    "connect_timeout_ms": 10_000,
    "total_timeout_ms": 30_000,
    "max_redirects": 5,
    "per_host_interval_ms": 1_000,
    "retries": 2,
    "robots_max_bytes": 512 * 1024,
    "respect_robots": True,
    "proxy_signatures": list(PROXY_SIGNATURES),
    "allow_loopback_ports": [],
    "loopback_only": False,
    "extraction": {"html": "html-stdlib/1", "plain": "plain/1"},
}


def _blob12(path):
    with open(path, "rb") as fh:
        return canonical.git_blob_sha1(fh.read())[:12]


def tool_version(cfg):
    here = os.path.dirname(os.path.abspath(__file__))
    cfgh = canonical.sha256_hex16(canonical_bytes(cfg))[:12]
    return "%s+%s.%s.k%s" % (
        SEMVER, _blob12(os.path.join(here, "capture.py")), _blob12(os.path.join(here, "canonical.py")), cfgh)


def make_config(**over):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    for k, v in over.items():
        if k not in cfg:
            raise KeyError(k)
        cfg[k] = v
    cfg["allow_loopback_ports"] = sorted(set(int(p) for p in cfg["allow_loopback_ports"]))
    if OLLAMA_PORT in cfg["allow_loopback_ports"]:
        raise ValueError("port 11434 (Ollama) can never be opened")
    canonical_json(cfg)  # no floats
    return cfg


# ── sanitization and extraction (§5.3) ──

_HSPACE = re.compile(r"[^\S\n]+")


def sanitize_text(s, max_chars):
    s = unicodedata.normalize("NFC", s)
    s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\u2028", "\n").replace("\u2029", "\n")
    s = "".join(ch for ch in s if ch == "\n" or ch == "\t" or unicodedata.category(ch) != "Cc")
    lines = (_HSPACE.sub(" ", ln).strip() for ln in s.split("\n"))
    s = "\n".join(ln for ln in lines if ln)
    return s[:max_chars]


_BLOCK = {"p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "table", "h1", "h2", "h3", "h4", "h5",
          "h6", "section", "article", "header", "footer", "nav", "aside", "main", "blockquote", "pre",
          "title", "dt", "dd", "figcaption", "hr", "form", "address"}
_SKIP = {"script", "style", "noscript", "template"}


class _HTMLText(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0
        self.license = None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag in _SKIP:
            self.skip += 1
        elif tag in _BLOCK:
            self.parts.append("\n")
        if self.license is None:
            if tag in ("link", "a") and "license" in a.get("rel", "").lower().split():
                self.license = a.get("href") or None
            elif tag == "meta" and a.get("name", "").lower() in ("license", "dc.rights", "dcterms.license", "dc.license"):
                self.license = a.get("content") or None

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in _SKIP:
            self.skip -= 1

    def handle_endtag(self, tag):
        if tag in _SKIP and self.skip:
            self.skip -= 1
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def license_slug(v):
    if not v:
        return None
    m = re.search(r"creativecommons\.org/(?:licenses|publicdomain)/([a-z\-]+)/(\d(?:\.\d)?)", v, re.I)
    if m:
        return "cc-%s-%s" % (m.group(1).lower(), m.group(2))
    return v.strip()[:200] or None


def _charset(content_type_header, body):
    m = re.search(r"charset=\"?([\w\-:.]+)", content_type_header or "", re.I)
    cs = m.group(1) if m else None
    if not cs:
        m = re.search(rb"<meta[^>]+charset=[\"']?([\w\-:.]+)", body[:4096], re.I)
        cs = m.group(1).decode("ascii", "replace") if m else None
    try:
        if cs:
            "".encode(cs)
            return cs
    except LookupError:
        pass
    return "utf-8"


def extract_text(media_type, ct_header, body, cfg):
    """Returns (method, text, license) or (None, None, None) for unsupported types."""
    if media_type in ("text/html", "application/xhtml+xml"):
        p = _HTMLText()
        try:
            p.feed(body.decode(_charset(ct_header, body), errors="replace"))
            p.close()
        except Exception:  # html.parser is lenient; be defensive anyway
            pass
        return cfg["extraction"]["html"], sanitize_text("".join(p.parts), cfg["max_text_chars"]), license_slug(p.license)
    if media_type == "text/plain":
        return cfg["extraction"]["plain"], sanitize_text(body.decode(_charset(ct_header, body), errors="replace"), cfg["max_text_chars"]), None
    return None, None, None


def is_proxy_block(body, cfg):
    head = body[:65536].decode("utf-8", errors="replace").lower()
    return any(re.search(sig, head, re.I | re.S) for sig in cfg["proxy_signatures"])


# ── SSRF guard (§5.2) ──

class SSRFBlocked(Exception):
    pass


def check_ip(ip_str, port, cfg):
    ip = ipaddress.ip_address(ip_str.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if isinstance(ip, ipaddress.IPv6Address) and ip.sixtofour is not None:
        ip = ip.sixtofour
    if ip.is_loopback:
        if port == OLLAMA_PORT:
            raise SSRFBlocked("loopback Ollama port %s:%d" % (ip, port))
        if port in cfg["allow_loopback_ports"]:
            return
        raise SSRFBlocked("loopback %s" % ip)
    if cfg["loopback_only"]:
        raise SSRFBlocked("test mode: non-loopback %s refused" % ip)
    if (not ip.is_global) or ip.is_multicast or ip.is_reserved or ip.is_unspecified or ip.is_link_local or ip.is_private:
        raise SSRFBlocked("non-global address %s" % ip)


def default_resolver(host, port):
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({i[4][0] for i in infos})


# ── HTTP plumbing ──

class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, port, ip, timeout, context):
        super().__init__(host, port, timeout=timeout, context=context)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def tls_context(ca_file=None):
    ctx = ssl.create_default_context()  # honours SSL_CERT_FILE / SSL_CERT_DIR
    if ca_file:
        ctx.load_verify_locations(cafile=ca_file)
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    return ctx


class _Fail(Exception):
    def __init__(self, outcome, detail=""):
        super().__init__(outcome, detail)
        self.outcome = outcome
        self.detail = detail


def _classify_exc(e):
    if isinstance(e, (ssl.SSLCertVerificationError, ssl.SSLError, ssl.CertificateError)):
        return "tls_error"
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "timeout"
    return "connect_error"


def _decode_body(raw, encoding, limit):
    """Undo gzip/deflate content-coding with a bounded output (no bombs)."""
    enc = (encoding or "identity").lower().strip()
    if enc in ("identity", ""):
        return raw, False
    if enc in ("gzip", "x-gzip", "deflate"):
        wbits = 16 + zlib.MAX_WBITS if "gzip" in enc else zlib.MAX_WBITS
        d = zlib.decompressobj(wbits)
        try:
            out = d.decompress(raw, limit + 1)
        except zlib.error:
            if enc == "deflate":
                d = zlib.decompressobj(-zlib.MAX_WBITS)
                out = d.decompress(raw, limit + 1)
            else:
                raise
        return out, len(out) > limit
    return raw, False


class Session:
    """One capture run: rate limiter, robots cache, TLS context, resolver."""

    def __init__(self, cfg, resolver=None, ca_file=None, clock=time.monotonic, sleep=time.sleep):
        self.cfg = cfg
        self.resolver = resolver or default_resolver
        self.ctx = tls_context(ca_file)
        self.clock = clock
        self.sleep = sleep
        self.last = {}
        self.robots = {}
        self.lock = threading.Lock()
        self.version = tool_version(cfg)

    # rate limit: 1 request / per_host_interval_ms per host
    def _wait(self, host):
        iv = self.cfg["per_host_interval_ms"] / 1000.0
        with self.lock:
            now = self.clock()
            t = self.last.get(host)
            if t is not None and now - t < iv:
                self.sleep(iv - (now - t))
            self.last[host] = self.clock()

    def _vet(self, url, tel):
        try:
            p = urllib.parse.urlsplit(url)
            scheme = p.scheme.lower()
            host = p.hostname
            port = p.port
        except ValueError:
            raise _Fail("invalid_identifier", "unparseable URL")
        if scheme not in ("http", "https"):
            raise SSRFBlocked("scheme %r" % p.scheme)
        if not host:
            raise _Fail("invalid_identifier", "no host")
        if p.username or p.password:
            raise _Fail("invalid_identifier", "credentials in URL")
        port = port or (443 if scheme == "https" else 80)
        ips = None
        try:
            ips = [str(ipaddress.ip_address(host))]
        except ValueError:
            if re.fullmatch(r"[0-9a-fA-FxX.]+", host) and not re.search(r"[g-wyzG-WYZ]", host):
                try:  # legacy numeric forms: 2130706433, 0x7f.1, 127.1
                    ips = [socket.inet_ntoa(socket.inet_aton(host))]
                except OSError:
                    ips = None
        if ips is None:
            if host.lower() == "localhost" or host.lower().endswith(".localhost"):
                ips = ["127.0.0.1"]
            else:
                try:
                    ips = self.resolver(host, port)
                except socket.gaierror as e:
                    if e.errno in (socket.EAI_NONAME, getattr(socket, "EAI_NODATA", -5)):
                        raise _Fail("dns_nxdomain", str(e))
                    raise _Fail("connect_error", "dns: %s" % e)
                except UnicodeError:
                    raise _Fail("invalid_identifier", "bad hostname")
        if not ips:
            raise _Fail("dns_nxdomain", "no addresses")
        tel.setdefault("resolved_ips", {})[host] = list(ips)
        for ip in ips:  # every address must pass, not just the one we use
            check_ip(ip, port, self.cfg)
        return p.scheme.lower(), host, port, ips[0], (p.path or "/") + ("?" + p.query if p.query else "")

    def _request_once(self, scheme, host, port, ip, target, deadline, max_bytes, tel):
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise _Fail("timeout", "total timeout")
        to = min(self.cfg["connect_timeout_ms"] / 1000.0, remaining)
        if scheme == "https":
            conn = _PinnedHTTPS(host, port, ip, to, self.ctx)
        else:
            conn = _PinnedHTTP(host, port, ip, to)
        try:
            conn.putrequest("GET", target, skip_accept_encoding=True)
            conn.putheader("User-Agent", "%s/%s (research; contact bran-paper repo)" % (UA_TOKEN, SEMVER))
            conn.putheader("Accept", "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1")
            conn.putheader("Accept-Encoding", "identity")
            conn.putheader("Connection", "close")
            conn.endheaders()
            if scheme == "https" and conn.sock is not None:
                try:
                    cert = conn.sock.getpeercert() or {}
                    issuer = ", ".join("=".join(x) for rdn in cert.get("issuer", ()) for x in rdn)
                    tel["tls_issuer"] = issuer
                    tel["tls_interception_suspected"] = any(h in issuer.lower() for h in PROXY_CA_HINTS)
                except Exception:
                    pass
            resp = conn.getresponse()
            chunks, total, truncated = [], 0, False
            while True:
                if self.clock() > deadline:
                    raise _Fail("timeout", "total timeout during body")
                if conn.sock is not None:
                    conn.sock.settimeout(max(0.05, min(to, deadline - self.clock())))
                c = resp.read(min(65536, max_bytes + 1 - total))
                if not c:
                    break
                chunks.append(c)
                total += len(c)
                if total > max_bytes:
                    truncated = True
                    break
            body = b"".join(chunks)
            body, dtrunc = _decode_body(body, resp.getheader("Content-Encoding"), max_bytes)
            if len(body) > max_bytes:
                body = body[:max_bytes]
                truncated = True
            truncated = truncated or dtrunc
            headers = {k: resp.getheader(k) for k in ("Content-Type", "Location", "Date", "ETag", "Last-Modified", "Server")}
            return resp.status, headers, body, truncated
        except _Fail:
            raise
        except Exception as e:
            raise _Fail(_classify_exc(e), "%s: %s" % (type(e).__name__, e))
        finally:
            conn.close()

    def _request(self, url, deadline, max_bytes, tel):
        scheme, host, port, ip, target = self._vet(url, tel)
        attempt = 0
        while True:
            self._wait(host)
            try:
                status, headers, body, trunc = self._request_once(scheme, host, port, ip, target, deadline, max_bytes, tel)
                if (status >= 500 or status == 429) and attempt < self.cfg["retries"]:
                    attempt += 1
                    tel["retries"] = tel.get("retries", 0) + 1
                    continue
                return status, headers, body, trunc
            except _Fail as f:
                if f.outcome in _TRANSIENT_RETRY and attempt < self.cfg["retries"] and self.clock() < deadline:
                    attempt += 1
                    tel["retries"] = tel.get("retries", 0) + 1
                    continue
                raise

    def robots_check(self, url, tel):
        """Returns {checked, allowed, robots_sha256} for url's origin."""
        p = urllib.parse.urlsplit(url)
        origin = "%s://%s" % (p.scheme.lower(), p.netloc.lower())
        if origin not in self.robots:
            res = {"checked": True, "allowed": None, "robots_sha256": None, "_parser": None}
            rurl = origin + "/robots.txt"
            deadline = self.clock() + self.cfg["total_timeout_ms"] / 1000.0
            try:
                for _ in range(self.cfg["max_redirects"] + 1):
                    status, headers, body, _t = self._request(rurl, deadline, self.cfg["robots_max_bytes"], tel)
                    if status in (301, 302, 303, 307, 308) and headers.get("Location"):
                        rurl = urllib.parse.urljoin(rurl, headers["Location"])
                        continue
                    break
                if 200 <= status < 300:
                    rp = urllib.robotparser.RobotFileParser()
                    rp.parse(body.decode("utf-8", errors="replace").splitlines())
                    res["robots_sha256"] = sha256_hex(body)
                    res["_parser"] = rp
                elif status in (401, 403):
                    res["allowed"] = False
                elif 400 <= status < 500:
                    res["allowed"] = True  # no robots.txt: everything allowed
                # 5xx -> unreachable, allowed stays None
            except (_Fail, SSRFBlocked) as e:
                tel.setdefault("robots_errors", []).append(str(e))
            self.robots[origin] = res
        res = self.robots[origin]
        out = {k: v for k, v in res.items() if not k.startswith("_")}
        if res["_parser"] is not None:
            out["allowed"] = bool(res["_parser"].can_fetch(UA_TOKEN, url))
        return out

    def capture(self, kind, requested, request_url):
        """Fetch one identifier. Returns (record, telemetry, body_or_None, text_or_None)."""
        cfg = self.cfg
        t0 = time.time()
        tel = {"fetched_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
               "retries": 0}
        rec = {
            "format": FORMAT, "requested": requested, "identifier_kind": kind, "request_url": request_url,
            "redirects": [], "resolved_url": None, "canonical_url": None, "http_status": None,
            "content_type": None, "content_length": 0, "truncated": False, "content_sha256": None,
            "extraction": None, "outcome": None,
            "robots": {"checked": False, "allowed": None, "robots_sha256": None},
            "license_note": None, "capture_tool_version": self.version,
        }
        body = text = None
        try:
            if kind == "isbn" or not request_url:
                raise _Fail("unsupported_identifier")
            if not isinstance(request_url, str) or len(request_url) > 2048 or re.search(r"[\x00-\x20\x7f]", request_url):
                raise _Fail("invalid_identifier", "bad characters")
            deadline = self.clock() + cfg["total_timeout_ms"] / 1000.0
            url = request_url
            seen = {url}
            while True:
                try:  # SSRF before robots, so a blocked host is never contacted
                    self._vet(url, tel)
                except SSRFBlocked:
                    if rec["redirects"]:
                        tel["blocked_url"] = url
                    raise
                if cfg["respect_robots"]:
                    rec["robots"] = self.robots_check(url, tel)
                    if rec["robots"]["allowed"] is False:
                        raise _Fail("robots_disallowed", url)
                status, headers, rbody, trunc = self._request(url, deadline, cfg["max_body_bytes"], tel)
                tel["response_headers"] = {k: v for k, v in headers.items() if k in ("Date", "ETag", "Last-Modified", "Server") and v}
                if status in (301, 302, 303, 307, 308) and headers.get("Location"):
                    nxt = urllib.parse.urljoin(url, headers["Location"].strip())
                    if len(rec["redirects"]) >= cfg["max_redirects"] or nxt in seen:
                        if len(rec["redirects"]) < cfg["max_redirects"]:
                            rec["redirects"].append({"url": url, "status": status})
                        raise _Fail("too_many_redirects", nxt)
                    rec["redirects"].append({"url": url, "status": status})
                    seen.add(nxt)
                    url = nxt
                    continue
                break
            rec["resolved_url"] = url
            rec["canonical_url"] = canonical.canonical_url(url)
            rec["http_status"] = status
            ct = headers.get("Content-Type") or ""
            media = ct.split(";")[0].strip().lower() or None
            rec["content_type"] = media
            rec["content_length"] = len(rbody)
            rec["truncated"] = bool(trunc)
            rec["content_sha256"] = sha256_hex(rbody)
            body = rbody
            textish = media in (None, "text/html", "application/xhtml+xml", "text/plain")
            if textish and is_proxy_block(rbody, cfg) and (200 <= status < 300 or status in (403, 407)):
                raise _Fail("blocked_proxy")
            if status in (404, 410):
                if kind == "doi" and not rec["redirects"]:
                    raise _Fail("invalid_identifier", "DOI resolver 404")
                raise _Fail("not_found")
            if not (200 <= status < 300):
                raise _Fail("http_error", str(status))
            method, txt, lic = extract_text(media, ct, rbody, cfg)
            if method is None:
                rec["outcome"] = "ok_no_text"
            else:
                rec["extraction"] = {"method": method, "method_version": "1",
                                     "text_sha256": sha256_hex(txt.encode("utf-8")), "text_chars": len(txt)}
                rec["license_note"] = lic
                text = txt
                rec["outcome"] = "ok" if len(txt) >= cfg["min_text_chars"] else "ok_no_text"
        except SSRFBlocked as e:
            rec["outcome"] = "blocked_ssrf"
            tel["detail"] = str(e)
        except _Fail as f:
            rec["outcome"] = f.outcome
            tel["detail"] = f.detail
        tel["duration_ms"] = int((time.time() - t0) * 1000)
        assert rec["outcome"] in OUTCOMES
        return rec, tel, body, text


# ── content-addressed cache (§1.5) ──

class CacheMiss(LookupError):
    pass


class CacheCorrupt(RuntimeError):
    pass


class Cache:
    def __init__(self, root):
        self.root = os.path.abspath(root)

    def _p(self, *parts):
        return os.path.join(self.root, *parts)

    @staticmethod
    def _write_once(path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            with open(path, "rb") as fh:
                if fh.read() != data:
                    raise CacheCorrupt("existing file differs: %s" % path)
            return
        tmp = path + ".tmp.%d" % os.getpid()
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)

    def blob_path(self, h):
        return self._p("blobs", "sha256", h[:2], h)

    def text_path(self, t):
        return self._p("text", "sha256", t[:2], t + ".txt")

    def record_path(self, cid):
        return self._p("captures", cid + ".json")

    def put(self, epoch, rec, tel, body, text):
        if body is not None:
            self._write_once(self.blob_path(rec["content_sha256"]), body)
        if text is not None:
            self._write_once(self.text_path(rec["extraction"]["text_sha256"]), text.encode("utf-8"))
        cid = record_id(rec)
        self._write_once(self.record_path(cid), canonical_bytes(rec))
        tp = self._p("captures", cid + ".telemetry.json")
        hist = []
        if os.path.exists(tp):
            with open(tp, encoding="utf-8") as fh:
                hist = json.load(fh)
        hist.append(tel)
        with open(tp, "w", encoding="utf-8") as fh:
            json.dump(hist, fh, indent=1, sort_keys=True)
        os.makedirs(self._p("index"), exist_ok=True)
        with open(self._p("index", "captures.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(canonical_json({"epoch": epoch, "request_url": rec["request_url"], "capture_id": cid}) + "\n")
        return cid

    def lookup(self, epoch, request_url):
        """capture_id for (epoch, request_url) or None. Reads index only."""
        ip = self._p("index", "captures.jsonl")
        if not os.path.exists(ip):
            return None
        found = None
        with open(ip, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                e = json.loads(line)
                if e["epoch"] == epoch and e["request_url"] == request_url:
                    found = e["capture_id"]
                    break  # first capture in an epoch is authoritative
        return found

    def load(self, cid):
        """Sealed record bytes, verified against the id."""
        p = self.record_path(cid)
        if not os.path.exists(p):
            raise CacheMiss(cid)
        with open(p, "rb") as fh:
            data = fh.read()
        rec = json.loads(data)
        if record_id(rec) != cid or canonical_bytes(rec) != data:
            raise CacheCorrupt("record %s does not hash to its id" % cid)
        return rec, data

    def verify(self):
        problems = []
        for sub, check in (("blobs", "blob"), ("text", "text")):
            base = self._p(sub, "sha256")
            if not os.path.isdir(base):
                continue
            for d in sorted(os.listdir(base)):
                for name in sorted(os.listdir(os.path.join(base, d))):
                    p = os.path.join(base, d, name)
                    with open(p, "rb") as fh:
                        h = sha256_hex(fh.read())
                    want = name[:-4] if check == "text" else name
                    if h != want or d != want[:2]:
                        problems.append("%s hash mismatch: %s" % (check, p))
        cdir = self._p("captures")
        ids = set()
        if os.path.isdir(cdir):
            for name in sorted(os.listdir(cdir)):
                if not name.endswith(".json") or name.endswith(".telemetry.json"):
                    continue
                cid = name[:-5]
                ids.add(cid)
                try:
                    rec, _ = self.load(cid)
                except (CacheCorrupt, ValueError) as e:
                    problems.append("record %s: %s" % (cid, e))
                    continue
                if rec.get("content_sha256") and not os.path.exists(self.blob_path(rec["content_sha256"])):
                    problems.append("record %s: missing blob %s" % (cid, rec["content_sha256"]))
                ex = rec.get("extraction")
                if ex and not os.path.exists(self.text_path(ex["text_sha256"])):
                    problems.append("record %s: missing text %s" % (cid, ex["text_sha256"]))
        ip = self._p("index", "captures.jsonl")
        if os.path.exists(ip):
            with open(ip, encoding="utf-8") as fh:
                for n, line in enumerate(fh, 1):
                    if not line.strip():
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        problems.append("index line %d: not JSON" % n)
                        continue
                    if e.get("capture_id") not in ids:
                        problems.append("index line %d: dangling capture_id %s" % (n, e.get("capture_id")))
        return problems


def capture_all(idents, cache, epoch, offline=False, session=None):
    """idents: iterable of {kind, requested, request_url}. Returns list of
    (ident, capture_id, record). Offline: index + captures only; any miss
    raises CacheMiss before anything is returned (nothing is written)."""
    out = []
    if offline:
        for it in idents:
            cid = cache.lookup(epoch, it["request_url"])
            if cid is None:
                raise CacheMiss("%s (epoch %s)" % (it["request_url"], epoch))
            rec, _ = cache.load(cid)
            out.append((it, cid, rec))
        return out
    if session is None:
        raise ValueError("online capture needs a Session")
    for it in idents:
        cid = cache.lookup(epoch, it["request_url"])
        if cid is not None:  # one record per (identifier, epoch)
            rec, _ = cache.load(cid)
        else:
            rec, tel, body, text = session.capture(it["kind"], it["requested"], it["request_url"])
            cid = cache.put(epoch, rec, tel, body, text)
        out.append((it, cid, rec))
    return out


# ── CLI ──

def _read_ids(args):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import extract
    items = []
    for raw in args.id or []:
        found = extract.find_identifiers(raw)
        if not found:
            items.append({"kind": "url", "requested": raw, "request_url": raw})
        items.extend({k: d[k] for k in ("kind", "requested", "request_url")} for d in found[:1])
    if args.ids:
        with open(args.ids, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("{"):
                    d = json.loads(line)
                    req = d["requested"]
                    items.append({"kind": d["kind"], "requested": req,
                                  "request_url": d.get("request_url") or extract.request_url(d["kind"], req)})
                else:
                    for d in extract.find_identifiers(line)[:1]:
                        items.append({k: d[k] for k in ("kind", "requested", "request_url")})
    seen, uniq = set(), []
    for it in items:
        key = (it["kind"], it["requested"])
        if key not in seen:
            seen.add(key)
            uniq.append(it)
    return uniq


def cmd_capture(args):
    idents = _read_ids(args)
    cache = Cache(args.cache)
    ports = [int(p) for p in args.allow_loopback_for_tests.split(",")] if args.allow_loopback_for_tests else []
    try:
        if args.offline:
            res = capture_all(idents, cache, args.epoch, offline=True)
        else:
            if not ports and not args.network_approved:
                print("refusing online capture: network gate Q5 not approved "
                      "(pass --network-approved once it is, or use --offline)", file=sys.stderr)
                return 2
            cfg = make_config(allow_loopback_ports=ports, loopback_only=bool(ports))
            sess = Session(cfg, ca_file=args.ca_file)
            res = capture_all(idents, cache, args.epoch, session=sess)
    except CacheMiss as e:
        print("cache miss (offline): %s" % e, file=sys.stderr)
        return 3
    except CacheCorrupt as e:
        print("cache corrupt: %s" % e, file=sys.stderr)
        return 4
    dist = {}
    lines = []
    for it, cid, rec in res:
        dist[rec["outcome"]] = dist.get(rec["outcome"], 0) + 1
        lines.append(canonical_json({"kind": it["kind"], "requested": it["requested"],
                                     "capture_id": cid, "outcome": rec["outcome"]}))
    data = "\n".join(lines) + ("\n" if lines else "")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(data)
    else:
        sys.stdout.write(data)
    print(json.dumps({"captured": len(res), "outcomes": dict(sorted(dist.items()))}), file=sys.stderr)
    return 0


def cmd_verify(args):
    problems = Cache(args.cache).verify()
    for p in problems:
        print(p)
    print("verify-cache: %s (%d problems)" % ("FAIL" if problems else "OK", len(problems)), file=sys.stderr)
    return 1 if problems else 0


def cmd_version(args):
    print(tool_version(make_config()))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="bran-capture/1 evidence capture")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("capture")
    p.add_argument("--ids", help="file: JSONL from extract.py ids, or one identifier per line")
    p.add_argument("--id", action="append", help="single identifier (repeatable)")
    p.add_argument("--cache", required=True)
    p.add_argument("--epoch", default="e0")
    p.add_argument("--offline", action="store_true", help="read only the cache; a miss exits 3 and writes nothing")
    p.add_argument("--network-approved", action="store_true", help="assert gate Q5 is approved (required for real fetches)")
    p.add_argument("--allow-loopback-for-tests", metavar="PORT[,PORT]", help="tests only: open these loopback ports and refuse everything else")
    p.add_argument("--ca-file", help="extra CA bundle (corporate TLS interception); verification stays on")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_capture)
    p = sub.add_parser("verify-cache")
    p.add_argument("--cache", required=True)
    p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("version")
    p.set_defaults(fn=cmd_version)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
