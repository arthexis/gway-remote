"""HTTP boundary tests using local threads only; never calls Agent Ops."""
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.mcp_bearer_gateway import make_server

class Upstream(BaseHTTPRequestHandler):
    seen = []
    def log_message(self, *args):
        pass
    def do_POST(self):
        self.__class__.seen.append(self.headers.get("Authorization"))
        raw = b\x27{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}\x27
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

class GatewayHttpTests(unittest.TestCase):
    def test_fail_closed_and_upstream_credentials(self):
        with tempfile.TemporaryDirectory() as home:
            registry = BearerRegistry(Path(home) / "db" / "tokens.sqlite3")
            token = registry.issue()
            verifier = BearerVerifier(registry.path)
            with ThreadingHTTPServer(("127.0.0.1", 0), Upstream) as upstream:
                t1 = threading.Thread(target=upstream.serve_forever, daemon=True)
                t1.start()
                url_up = "http://127.0.0.1:%d/mcp" % upstream.server_port
                with make_server(("127.0.0.1", 0), verifier, url_up, "backend-secret") as gateway:
                    t2 = threading.Thread(target=gateway.serve_forever, daemon=True)
                    t2.start()
                    url = "http://127.0.0.1:%d" % gateway.server_port
                    payload = json.dumps({"jsonrpc":"2.0","id":1,"method":"tools/list"}).encode()
                    def send(bearer=None, path="/mcp", body=payload):
                        headers = {"Content-Type":"application/json"}
                        if bearer is not None:
                            headers["Authorization"] = "Bearer " + bearer
                        req = Request(url + path, body, headers, method="POST")
                        try:
                            with urlopen(req, timeout=3) as response:
                                return response.status
                        except HTTPError as exc:
                            return exc.code
                    before = len(Upstream.seen)
                    self.assertEqual(send(), 401)
                    self.assertEqual(send("wrong"), 401)
                    self.assertEqual(send(token, path="/other"), 404)
                    denied = json.dumps({"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"agent_submit"}}).encode()
                    self.assertEqual(send(token, body=denied), 403)
                    self.assertEqual(len(Upstream.seen), before)
                    self.assertEqual(send(token), 200)
                    self.assertEqual(Upstream.seen[-1], "Bearer backend-secret")
                    self.assertTrue(registry.revoke(token.split("_")[1]))
                    self.assertEqual(send(token), 401)
                    gateway.shutdown()
                upstream.shutdown()

if __name__ == "__main__":
    unittest.main()
