"""HTTP boundary tests using local threads only; never calls Agent Ops."""
import json
import tempfile
import threading
import unittest
from unittest.mock import Mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.mcp_bearer_gateway import make_server, MAX_RESPONSE

class Upstream(BaseHTTPRequestHandler):
    seen = []
    def log_message(self, *args):
        pass
    def do_POST(self):
        self.__class__.seen.append(self.headers.get("Authorization"))
        raw = b'{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

class GatewayHttpTests(unittest.TestCase):
    def test_agent_deadline_fits_gateway_budget_without_unbounded_response(self):
        """Model a 20s adapter response without sleeping or invoking Agent Ops."""
        with tempfile.TemporaryDirectory() as home:
            registry = BearerRegistry(Path(home) / "tokens.sqlite3")
            token = registry.issue()
            with make_server(("127.0.0.1", 0), BearerVerifier(registry.path),
                             "http://127.0.0.1:1/mcp", "backend-secret") as gateway:
                response = Mock(status=200, headers={"Content-Type": "application/json"})
                response.read.return_value = b'{"jsonrpc":"2.0","id":1,"result":{}}'
                context = Mock()
                context.__enter__ = Mock(return_value=response)
                context.__exit__ = Mock(return_value=False)
                def adapter_response(request, *, timeout):
                    # Independent adapter contract: timeout=20 in Agent Ops.
                    # The old 8s proxy deadline truncates a valid bounded call.
                    if timeout <= 20:
                        raise TimeoutError("adapter result not ready")
                    self.assertLessEqual(timeout, 30)
                    return context
                gateway.opener.open = Mock(side_effect=adapter_response)
                thread = threading.Thread(target=gateway.serve_forever, daemon=True)
                thread.start()
                try:
                    url = "http://127.0.0.1:%d/mcp" % gateway.server_port
                    body = json.dumps({"jsonrpc":"2.0","id":1,"method":"tools/call",
                                       "params":{"name":"agent_list_issues","arguments":{}}}).encode()
                    request = Request(url, body, {"Authorization":"Bearer " + token,
                                      "Content-Type":"application/json"}, method="POST")
                    with urlopen(request, timeout=3) as result:
                        self.assertEqual(result.status, 200)
                        self.assertIn(b'"result"', result.read())
                    response.read.assert_called_once_with(MAX_RESPONSE + 1)
                    response.read.return_value = b"x" * (MAX_RESPONSE + 1)
                    with self.assertRaises(HTTPError) as rejected:
                        urlopen(request, timeout=3)
                    self.assertEqual(rejected.exception.code, 502)
                    rejected.exception.close()
                    gateway.opener.open.side_effect = TimeoutError("backend deadline")
                    with self.assertRaises(HTTPError) as timed_out:
                        urlopen(request, timeout=3)
                    self.assertEqual(timed_out.exception.code, 502)
                    timed_out.exception.close()
                finally:
                    gateway.shutdown()
                    thread.join()

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
