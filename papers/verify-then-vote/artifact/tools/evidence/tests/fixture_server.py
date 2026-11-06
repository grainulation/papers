"""Local fixture HTTP(S) server for capture tests. Binds 127.0.0.1 only.

Also provides NoNetwork, a guard that makes any socket connect to a
non-loopback address (or a loopback connect to the Ollama port) raise,
and records every connect attempt, so a test can prove no outbound
request was made.
"""

import gzip
import http.server
import os
import socket
import ssl
import subprocess
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")


def fixture(name):
    with open(os.path.join(FIX, name), "rb") as fh:
        return fh.read()


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "fixture/1"
    sys_version = ""

    def log_message(self, *a):
        pass

    def _send(self, status, body=b"", ctype="text/html; charset=utf-8", headers=()):
        try:
            self.send_response(status)
            if ctype:
                self.send_header("Content-Type", ctype)
            for k, v in headers:
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass

    def _redirect(self, status, loc):
        self._send(status, b"moved", headers=[("Location", loc)])

    def do_GET(self):  # noqa: C901
        srv = self.server
        path = self.path.split("?")[0]
        srv.hits[path] = srv.hits.get(path, 0) + 1
        srv.user_agents.append(self.headers.get("User-Agent"))
        if path == "/robots.txt":
            mode = srv.robots_mode
            if mode == "file":
                return self._send(200, fixture("robots.txt"), "text/plain")
            if mode == "404":
                return self._send(404, b"no robots")
            if mode == "500":
                return self._send(500, b"oops")
        routes = {
            "/live": lambda: self._send(200, fixture("live.html")),
            "/plain": lambda: self._send(200, fixture("plain.txt"), "text/plain; charset=utf-8"),
            "/short": lambda: self._send(200, fixture("short.html")),
            "/pdf": lambda: self._send(200, fixture("doc.pdf"), "application/pdf"),
            "/png": lambda: self._send(200, fixture("pixel.png"), "image/png"),
            "/proxy-block": lambda: self._send(200, fixture("proxy_block.html")),
            "/proxy-403": lambda: self._send(403, fixture("proxy_block.html")),
            "/missing": lambda: self._send(404, b"<h1>Not Found</h1>"),
            "/gone": lambda: self._send(410, b"<h1>Gone</h1>"),
            "/forbidden": lambda: self._send(403, b"<h1>Forbidden</h1>"),
            "/err500": lambda: self._send(500, b"<h1>Server error</h1>"),
            "/private/page": lambda: self._send(200, fixture("live.html")),
            "/r1": lambda: self._redirect(302, "/r2"),
            "/r2": lambda: self._redirect(301, "http://fixture.test:%d/r3" % srv.server_address[1]),
            "/r3": lambda: self._redirect(307, "/live/?utm_source=x&id=7#frag"),
            "/live/": lambda: self._send(200, fixture("live.html")),
            "/loop": lambda: self._redirect(302, "/loop"),
            "/to-private": lambda: self._redirect(302, "http://10.0.0.5/secret"),
            "/to-metadata": lambda: self._redirect(302, "http://169.254.169.254/latest/meta-data/"),
            "/to-ollama": lambda: self._redirect(302, "http://localhost:11434/api/tags"),
            "/to-evil-dns": lambda: self._redirect(302, "http://evil.test/x"),
            "/to-file": lambda: self._redirect(302, "file:///etc/passwd"),
            "/to-robots-denied": lambda: self._redirect(302, "/private/page"),
            "/big": lambda: self._send(200, b"<html><body><p>" + b"A" * (200 * 1024) + b"</p></body></html>"),
            "/gzip": lambda: self._send(200, gzip.compress(fixture("live.html"), mtime=0),
                                        headers=[("Content-Encoding", "gzip")]),
            "/latin1": lambda: self._send(200, ("<p>" + "Café crème. " * 30 + "</p>").encode("latin-1"),
                                          "text/html; charset=iso-8859-1"),
        }
        if path.startswith("/chain/"):
            n = int(path.rsplit("/", 1)[1])
            return self._redirect(302, "/chain/%d" % (n + 1))
        if path == "/slow":
            time.sleep(1.5)
            return self._send(200, fixture("live.html"))
        fn = routes.get(path)
        if fn is None:
            return self._send(404, b"no route")
        fn()


class FixtureServer:
    def __init__(self, robots_mode="file", tls_cert=None):
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.httpd.hits = {}
        self.httpd.user_agents = []
        self.httpd.robots_mode = robots_mode
        if tls_cert:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(*tls_cert)
            self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def hits(self):
        return self.httpd.hits

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()


def make_self_signed(dirpath, host="fixture.test"):
    """Self-signed cert via the openssl CLI; returns (cert, key) or None."""
    cert = os.path.join(dirpath, "cert.pem")
    key = os.path.join(dirpath, "key.pem")
    try:
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", cert,
             "-days", "1", "-subj", "/CN=%s" % host, "-addext", "subjectAltName=DNS:%s" % host],
            check=True, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return cert, key


def stub_resolver(table):
    def resolve(host, port):
        if host in table:
            return list(table[host])
        raise socket.gaierror(socket.EAI_NONAME, "stub: unknown host %s" % host)
    return resolve


class NoNetwork:
    """Patch socket connect/getaddrinfo: loopback only, never port 11434."""

    def __init__(self):
        self.attempts = []

    def __enter__(self):
        self._connect = socket.socket.connect
        self._connect_ex = socket.socket.connect_ex
        self._gai = socket.getaddrinfo
        guard = self

        def ok(addr):
            host, port = addr[0], addr[1]
            guard.attempts.append((host, port))
            if host not in ("127.0.0.1", "::1") or port == 11434:
                raise AssertionError("outbound connect attempted: %r" % (addr,))

        def connect(sock, addr):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                ok(addr)
            return guard._connect(sock, addr)

        def connect_ex(sock, addr):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                ok(addr)
            return guard._connect_ex(sock, addr)

        def gai(host, *a, **k):
            if host not in ("127.0.0.1", "::1", "localhost", None):
                raise AssertionError("DNS lookup attempted: %r" % host)
            return guard._gai(host, *a, **k)

        socket.socket.connect = connect
        socket.socket.connect_ex = connect_ex
        socket.getaddrinfo = gai
        return self

    def __exit__(self, *a):
        socket.socket.connect = self._connect
        socket.socket.connect_ex = self._connect_ex
        socket.getaddrinfo = self._gai


def tempdir():
    return tempfile.mkdtemp(prefix="overturn-evidence-test-")
