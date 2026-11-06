"""In-process mock of the Ollama HTTP API (/api/tags, /api/version, /api/generate) for tests.

MockOllama().responder is a function(body) -> (http_status, json_dict); requests are recorded.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIGEST = "6577803aa9a036369e481d648a2baebb381ebc6e897f2bb9a766a2aa7bfbc1cf"


def gen_ok(response, model="mistral:latest", done_reason="stop", prompt_eval_count=800, eval_count=20):
    return 200, {"model": model, "created_at": "2026-10-22T00:00:00Z", "response": response, "done": True,
                 "done_reason": done_reason, "total_duration": 1500000000, "load_duration": 1000000,
                 "prompt_eval_count": prompt_eval_count, "prompt_eval_duration": 900000000,
                 "eval_count": eval_count, "eval_duration": 500000000}


class MockOllama:
    def __init__(self, digest=DIGEST, version="0.17.7"):
        self.digest, self.version = digest, version
        self.requests = []
        self.responder = lambda body: gen_ok('{"label": "supports", "confidence": 9000}')
        mock = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                if self.path == "/api/tags":
                    self._send(200, {"models": [{"name": "mistral:latest", "digest": mock.digest,
                                                 "details": {"parameter_size": "7.2B",
                                                             "quantization_level": "Q4_K_M"}}]})
                elif self.path == "/api/version":
                    self._send(200, {"version": mock.version})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n).decode())
                mock.requests.append((self.path, body))
                if self.path != "/api/generate":
                    self._send(404, {"error": "not found"})
                    return
                code, obj = mock.responder(body)
                self._send(code, obj)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.endpoint = "http://127.0.0.1:%d" % self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.server.shutdown()
        self.server.server_close()

    def generate_calls(self):
        return [b for p, b in self.requests if p == "/api/generate"]
