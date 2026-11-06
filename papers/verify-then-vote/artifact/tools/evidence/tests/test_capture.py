"""Capture-tool acceptance tests against a local 127.0.0.1 fixture server.

Every test runs under NoNetwork: any connect to a non-loopback address,
any loopback connect to 11434, and any real DNS lookup raises. Hostnames
resolve through a stub resolver.
"""

import contextlib
import gzip
import hashlib
import io
import json
import os
import shutil
import socket
import ssl
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import capture  # noqa: E402
import canonical  # noqa: E402
from fixture_server import FixtureServer, NoNetwork, fixture, make_self_signed, stub_resolver, tempdir  # noqa: E402

RESOLVE = {"fixture.test": ["127.0.0.1"], "evil.test": ["10.0.0.1"], "mixed.test": ["127.0.0.1", "10.0.0.1"],
           "meta.test": ["169.254.169.254"], "v6ula.test": ["fd00::1"]}


class Base(unittest.TestCase):
    robots_mode = "file"

    @classmethod
    def setUpClass(cls):
        cls.srv = FixtureServer(robots_mode=cls.robots_mode).__enter__()
        cls.port = cls.srv.port

    @classmethod
    def tearDownClass(cls):
        cls.srv.__exit__()

    def setUp(self):
        self.guard = NoNetwork().__enter__()
        self.addCleanup(self.guard.__exit__)
        self.cache_dir = tempdir()
        self.addCleanup(shutil.rmtree, self.cache_dir, True)

    def cfg(self, **kw):
        base = dict(allow_loopback_ports=[self.port], loopback_only=True, per_host_interval_ms=0,
                    connect_timeout_ms=500, total_timeout_ms=4000, max_body_bytes=65536)
        base.update(kw)
        return capture.make_config(**base)

    def session(self, **kw):
        return capture.Session(self.cfg(**kw), resolver=stub_resolver(RESOLVE))

    def url(self, path, host="fixture.test"):
        return "http://%s:%d%s" % (host, self.port, path)

    def cap(self, path, sess=None, kind="url", host="fixture.test"):
        sess = sess or self.session()
        u = path if "://" in path else self.url(path, host)
        return sess.capture(kind, u, u)


class Outcomes(Base):
    def test_live_page(self):
        rec, tel, body, text = self.cap("/live")
        self.assertEqual(rec["outcome"], "ok")
        self.assertEqual(rec["http_status"], 200)
        self.assertEqual(rec["content_type"], "text/html")
        self.assertEqual(rec["content_sha256"], hashlib.sha256(fixture("live.html")).hexdigest())
        self.assertEqual(rec["content_length"], len(fixture("live.html")))
        self.assertEqual(rec["extraction"]["method"], "html-stdlib/1")
        self.assertEqual(rec["extraction"]["text_sha256"], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(rec["license_note"], "cc-by-4.0")
        self.assertIn("Canberra is the capital city of Australia.", text)
        self.assertIn("Café", text)
        self.assertNotIn("IGNORE ALL PREVIOUS", text)   # script dropped
        self.assertNotIn("color: red", text)            # style dropped
        self.assertNotIn("Enable JavaScript", text)     # noscript dropped
        self.assertNotIn("\x01", text)
        self.assertNotIn("\x7f", text)
        self.assertEqual(rec["robots"]["allowed"], True)
        self.assertIsNotNone(rec["robots"]["robots_sha256"])
        self.assertTrue(all(ua.startswith("bran-evidence-capture/") for ua in self.srv.httpd.user_agents))
        canonical.canonical_json(rec)  # no floats

    def test_plain_text(self):
        rec, _, _, text = self.cap("/plain")
        self.assertEqual(rec["outcome"], "ok")
        self.assertEqual(rec["extraction"]["method"], "plain/1")
        self.assertIn("TRANSMISSION CONTROL PROTOCOL", text)

    def test_404_and_410(self):
        self.assertEqual(self.cap("/missing")[0]["outcome"], "not_found")
        self.assertEqual(self.cap("/gone")[0]["outcome"], "not_found")

    def test_doi_resolver_404_is_invalid_identifier(self):
        u = self.url("/missing")
        rec = self.session().capture("doi", "10.9999/nope", u)[0]
        self.assertEqual(rec["outcome"], "invalid_identifier")

    def test_http_error_and_retries(self):
        self.assertEqual(self.cap("/forbidden")[0]["outcome"], "http_error")
        before = self.srv.hits.get("/err500", 0)
        rec, tel, _, _ = self.cap("/err500")
        self.assertEqual(rec["outcome"], "http_error")
        self.assertEqual(rec["http_status"], 500)
        self.assertEqual(self.srv.hits["/err500"] - before, 3)  # 1 + 2 retries
        self.assertEqual(tel["retries"], 2)

    def test_redirect_chain(self):
        rec = self.cap("/r1")[0]
        self.assertEqual(rec["outcome"], "ok")
        self.assertEqual([h["status"] for h in rec["redirects"]], [302, 301, 307])
        self.assertEqual(rec["redirects"][0]["url"], self.url("/r1"))
        self.assertEqual(rec["resolved_url"], self.url("/live/?utm_source=x&id=7#frag"))
        self.assertEqual(rec["canonical_url"], self.url("/live?id=7"))

    def test_too_many_redirects_and_loop(self):
        rec = self.cap("/chain/0")[0]
        self.assertEqual(rec["outcome"], "too_many_redirects")
        self.assertLessEqual(len(rec["redirects"]), 5)
        self.assertEqual(self.cap("/loop")[0]["outcome"], "too_many_redirects")

    def test_redirect_to_private_ip_blocked(self):
        for path in ("/to-private", "/to-metadata", "/to-ollama", "/to-evil-dns", "/to-file"):
            rec, tel, _, _ = self.cap(path)
            self.assertEqual(rec["outcome"], "blocked_ssrf", path)
            self.assertEqual(len(rec["redirects"]), 1, path)
            self.assertIsNone(rec["resolved_url"], path)
        for h, p in self.guard.attempts:
            self.assertEqual((h, p), ("127.0.0.1", self.port))

    def test_oversized_body_truncated(self):
        rec, _, body, text = self.cap("/big")
        self.assertEqual(rec["outcome"], "ok")
        self.assertTrue(rec["truncated"])
        self.assertEqual(rec["content_length"], 65536)
        self.assertEqual(len(body), 65536)
        self.assertEqual(rec["content_sha256"], hashlib.sha256(body).hexdigest())

    def test_text_cap(self):
        rec, _, _, text = self.cap("/big", self.session(max_text_chars=1000))
        self.assertEqual(rec["extraction"]["text_chars"], 1000)
        self.assertEqual(len(text), 1000)

    def test_proxy_block_page(self):
        self.assertEqual(self.cap("/proxy-block")[0]["outcome"], "blocked_proxy")
        self.assertEqual(self.cap("/proxy-403")[0]["outcome"], "blocked_proxy")

    def test_non_html(self):
        rec = self.cap("/pdf")[0]
        self.assertEqual((rec["outcome"], rec["content_type"], rec["extraction"]), ("ok_no_text", "application/pdf", None))
        rec = self.cap("/png")[0]
        self.assertEqual((rec["outcome"], rec["content_type"]), ("ok_no_text", "image/png"))

    def test_js_only_page(self):
        rec = self.cap("/short")[0]
        self.assertEqual(rec["outcome"], "ok_no_text")
        self.assertLess(rec["extraction"]["text_chars"], 200)

    def test_gzip_and_charset(self):
        rec, _, body, text = self.cap("/gzip")
        self.assertEqual(rec["outcome"], "ok")
        self.assertEqual(body, fixture("live.html"))
        rec, _, _, text = self.cap("/latin1")
        self.assertIn("Café crème", text)

    def test_robots_disallowed(self):
        before = self.srv.hits.get("/private/page", 0)
        rec = self.cap("/private/page")[0]
        self.assertEqual(rec["outcome"], "robots_disallowed")
        self.assertFalse(rec["robots"]["allowed"])
        self.assertEqual(self.srv.hits.get("/private/page", 0), before)  # never fetched
        rec = self.cap("/to-robots-denied")[0]
        self.assertEqual(rec["outcome"], "robots_disallowed")

    def test_timeout(self):
        rec, tel, _, _ = self.cap("/slow", self.session(retries=0))
        self.assertEqual(rec["outcome"], "timeout")

    def test_dns_nxdomain(self):
        rec = self.cap("http://no-such-host.test/x")[0]
        self.assertEqual(rec["outcome"], "dns_nxdomain")

    def test_connect_error(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        closed = s.getsockname()[1]
        s.close()
        sess = capture.Session(self.cfg(allow_loopback_ports=[self.port, closed], retries=0), resolver=stub_resolver(RESOLVE))
        u = "http://127.0.0.1:%d/x" % closed
        self.assertEqual(sess.capture("url", u, u)[0]["outcome"], "connect_error")

    def test_unsupported_and_invalid(self):
        sess = self.session()
        self.assertEqual(sess.capture("isbn", "9780134685991", None)[0]["outcome"], "unsupported_identifier")
        self.assertEqual(sess.capture("url", "http://[::1", "http://[::1")[0]["outcome"], "invalid_identifier")
        self.assertEqual(sess.capture("url", "http://a b/", "http://a b/")[0]["outcome"], "invalid_identifier")
        u = "http://user:pw@fixture.test:%d/live" % self.port
        self.assertEqual(sess.capture("url", u, u)[0]["outcome"], "invalid_identifier")


class SSRF(Base):
    def test_direct_blocks(self):
        sess = self.session()
        for u in ("http://127.0.0.1:11434/api/tags", "http://localhost:11434/api/tags", "http://localhost/",
                  "http://127.0.0.1:%d/live" % (self.port + 1 if self.port < 65535 else self.port - 1),
                  "http://10.1.2.3/", "http://192.168.1.1/", "http://172.16.0.1/", "http://169.254.169.254/latest/meta-data/",
                  "http://100.64.0.1/", "http://0.0.0.0/", "http://[::1]/", "http://[fd00::1]/", "http://[fe80::1]/",
                  "http://[::ffff:127.0.0.1]/", "http://[::ffff:10.0.0.1]/", "http://[2002:a00:1::]/",
                  "http://2130706433/", "http://0x7f.1/", "http://127.1/",
                  "http://evil.test/", "http://mixed.test/", "http://meta.test/", "http://v6ula.test/",
                  "file:///etc/passwd", "ftp://fixture.test/x", "gopher://fixture.test/"):
            rec = sess.capture("url", u, u)[0]
            self.assertEqual(rec["outcome"], "blocked_ssrf", u)
        self.assertEqual(self.guard.attempts, [])  # nothing was contacted

    def test_production_mode_blocks_loopback(self):
        sess = capture.Session(capture.make_config(per_host_interval_ms=0), resolver=stub_resolver(RESOLVE))
        u = self.url("/live")
        self.assertEqual(sess.capture("url", u, u)[0]["outcome"], "blocked_ssrf")
        self.assertEqual(self.guard.attempts, [])

    def test_test_mode_refuses_public(self):
        sess = capture.Session(self.cfg(), resolver=stub_resolver({"public.test": ["93.184.216.34"]}))
        u = "http://public.test/"
        self.assertEqual(sess.capture("url", u, u)[0]["outcome"], "blocked_ssrf")
        self.assertEqual(self.guard.attempts, [])

    def test_ollama_port_never_allowed(self):
        with self.assertRaises(ValueError):
            capture.make_config(allow_loopback_ports=[11434])

    def test_tls_verification_on(self):
        ctx = capture.tls_context()
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)


class Determinism(Base):
    def test_same_fixture_twice(self):
        a = self.cap("/r1", self.session())
        time.sleep(0.01)
        b = self.cap("/r1", self.session())
        self.assertEqual(canonical.canonical_bytes(a[0]), canonical.canonical_bytes(b[0]))
        self.assertEqual(canonical.record_id(a[0]), canonical.record_id(b[0]))
        self.assertNotEqual(a[1]["fetched_at"], b[1]["fetched_at"])

    def test_version_tracks_config(self):
        self.assertNotEqual(capture.tool_version(self.cfg()), capture.tool_version(self.cfg(max_body_bytes=1)))


class CacheTests(Base):
    PATHS = ("/live", "/plain", "/missing", "/r1", "/pdf", "/to-private")

    def idents(self):
        return [{"kind": "url", "requested": self.url(p), "request_url": self.url(p)} for p in self.PATHS]

    def warm(self):
        cache = capture.Cache(self.cache_dir)
        return cache, capture.capture_all(self.idents(), cache, "e1", session=self.session())

    def snapshot(self):
        out = {}
        for d, _, files in os.walk(self.cache_dir):
            for f in files:
                p = os.path.join(d, f)
                with open(p, "rb") as fh:
                    out[p] = fh.read()
        return out

    def test_layout(self):
        cache, res = self.warm()
        rec = res[0][2]
        self.assertTrue(os.path.exists(cache.blob_path(rec["content_sha256"])))
        self.assertTrue(os.path.exists(cache.text_path(rec["extraction"]["text_sha256"])))
        self.assertTrue(os.path.exists(cache.record_path(res[0][1])))
        self.assertTrue(os.path.exists(os.path.join(self.cache_dir, "captures", res[0][1] + ".telemetry.json")))
        with open(os.path.join(self.cache_dir, "index", "captures.jsonl")) as fh:
            lines = [json.loads(x) for x in fh]
        self.assertEqual(len(lines), len(self.PATHS))
        self.assertEqual(set(lines[0]), {"epoch", "request_url", "capture_id"})
        self.assertEqual(cache.verify(), [])

    def test_one_record_per_epoch(self):
        cache, res = self.warm()
        hits = self.srv.hits.get("/live")
        again = capture.capture_all(self.idents()[:1], cache, "e1", session=self.session())
        self.assertEqual(self.srv.hits.get("/live"), hits)  # reused, not refetched
        self.assertEqual(again[0][1], res[0][1])

    def test_offline_reproduces_and_miss_writes_nothing(self):
        cache, res = self.warm()
        snap = self.snapshot()
        self.guard.__exit__()
        with NoNetwork() as g:
            off = capture.capture_all(self.idents(), cache, "e1", offline=True)
            self.assertEqual(g.attempts, [])
        self.guard.__enter__()
        self.assertEqual([canonical.canonical_bytes(r) for _, _, r in off], [canonical.canonical_bytes(r) for _, _, r in res])
        with self.assertRaises(capture.CacheMiss):
            capture.capture_all(self.idents() + [{"kind": "url", "requested": "https://x.org/", "request_url": "https://x.org/"}],
                                cache, "e1", offline=True)
        with self.assertRaises(capture.CacheMiss):
            capture.capture_all(self.idents(), cache, "other-epoch", offline=True)
        self.assertEqual(self.snapshot(), snap)

    def test_cli_offline(self):
        self.warm()
        out = os.path.join(tempdir(), "out.jsonl")
        self.addCleanup(shutil.rmtree, os.path.dirname(out), True)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = capture.main(["capture", "--id", self.url("/live"), "--cache", self.cache_dir, "--epoch", "e1", "--offline", "--out", out])
        self.assertEqual(rc, 0)
        with open(out) as fh:
            self.assertEqual(json.loads(fh.readline())["outcome"], "ok")
        os.remove(out)
        snap = self.snapshot()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = capture.main(["capture", "--id", "https://missing.example/", "--cache", self.cache_dir, "--epoch", "e1", "--offline", "--out", out])
        self.assertEqual(rc, 3)
        self.assertFalse(os.path.exists(out))
        self.assertEqual(self.snapshot(), snap)

    def test_cli_online_requires_gate(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = capture.main(["capture", "--id", "https://example.org/", "--cache", self.cache_dir])
        self.assertEqual(rc, 2)
        self.assertIn("Q5", err.getvalue())
        self.assertEqual(self.guard.attempts, [])

    def test_cli_loopback_test_mode(self):
        u = "http://127.0.0.1:%d/live" % self.port
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()) as out:
            rc = capture.main(["capture", "--id", u, "--cache", self.cache_dir, "--allow-loopback-for-tests", str(self.port)])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out.getvalue().splitlines()[0])["outcome"], "ok")

    def _tamper(self, path):
        with open(path, "rb") as fh:
            data = bytearray(fh.read())
        data[len(data) // 2] ^= 0x01
        with open(path, "wb") as fh:
            fh.write(bytes(data))

    def test_verify_cache_detects_one_byte_changes(self):
        cache, res = self.warm()
        rec = res[0][2]
        targets = {
            "blob": lambda c: c.blob_path(rec["content_sha256"]),
            "text": lambda c: c.text_path(rec["extraction"]["text_sha256"]),
            "record": lambda c: c.record_path(res[0][1]),
        }
        for name, fn in targets.items():
            d = tempdir()
            self.addCleanup(shutil.rmtree, d, True)
            copy = os.path.join(d, "c")
            shutil.copytree(self.cache_dir, copy)
            c = capture.Cache(copy)
            self.assertEqual(c.verify(), [], name)
            self._tamper(fn(c))
            self.assertTrue(c.verify(), name)
        # telemetry edits are not integrity failures
        tp = os.path.join(self.cache_dir, "captures", res[0][1] + ".telemetry.json")
        with open(tp, "a") as fh:
            fh.write(" ")
        self.assertEqual(cache.verify(), [])


class RobotsAbsent(Base):
    robots_mode = "404"

    def test_no_robots_means_allowed(self):
        rec = self.cap("/private/page")[0]
        self.assertEqual(rec["outcome"], "ok")
        self.assertEqual(rec["robots"], {"checked": True, "allowed": True, "robots_sha256": None})


class RobotsUnreachable(Base):
    robots_mode = "500"

    def test_unreachable_robots_is_null(self):
        rec = self.cap("/live", self.session(retries=0))[0]
        self.assertEqual(rec["outcome"], "ok")
        self.assertIsNone(rec["robots"]["allowed"])


class RateLimit(Base):
    def test_one_request_per_interval_per_host(self):
        sess = self.session(per_host_interval_ms=300)
        t = time.monotonic()
        self.cap("/live", sess)   # robots + page
        self.cap("/plain", sess)  # page (robots cached)
        self.assertGreaterEqual(time.monotonic() - t, 0.55)


class TLS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempdir()
        cls.cert = make_self_signed(cls.dir)
        if cls.cert is None:
            raise unittest.SkipTest("openssl CLI unavailable")
        cls.srv = FixtureServer(tls_cert=cls.cert).__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.srv.__exit__()
        shutil.rmtree(cls.dir, True)

    def setUp(self):
        self.guard = NoNetwork().__enter__()
        self.addCleanup(self.guard.__exit__)

    def _sess(self, ca=None):
        cfg = capture.make_config(allow_loopback_ports=[self.srv.port], loopback_only=True, per_host_interval_ms=0,
                                  connect_timeout_ms=2000, retries=0)
        return capture.Session(cfg, resolver=stub_resolver({"fixture.test": ["127.0.0.1"]}), ca_file=ca)

    def test_untrusted_cert_is_tls_error(self):
        u = "https://fixture.test:%d/live" % self.srv.port
        rec, tel, _, _ = self._sess().capture("url", u, u)
        self.assertEqual(rec["outcome"], "tls_error")
        self.assertIn("CERTIFICATE_VERIFY_FAILED", tel["detail"] + " " + " ".join(tel.get("robots_errors", [])))

    def test_extra_ca_file_keeps_verification(self):
        u = "https://fixture.test:%d/live" % self.srv.port
        rec, tel, _, _ = self._sess(ca=self.cert[0]).capture("url", u, u)
        self.assertEqual(rec["outcome"], "ok")
        self.assertIn("fixture.test", tel["tls_issuer"])
        # wrong hostname with a trusted cert still fails
        sess = capture.Session(capture.make_config(allow_loopback_ports=[self.srv.port], loopback_only=True,
                                                   per_host_interval_ms=0, retries=0),
                               resolver=stub_resolver({"other.test": ["127.0.0.1"]}), ca_file=self.cert[0])
        u2 = "https://other.test:%d/live" % self.srv.port
        self.assertEqual(sess.capture("url", u2, u2)[0]["outcome"], "tls_error")


if __name__ == "__main__":
    unittest.main()
