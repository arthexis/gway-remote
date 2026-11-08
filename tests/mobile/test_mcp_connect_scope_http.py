from tests.helpers.mcp_http import pkce_s256
"""Real HTTP OAuth /connect regression: intentional scope choice, no upgrades."""
import http.client
import re
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

from gway_remote.mcp_bearer import BearerRegistry
from gway_remote.mcp_link import LinkFlow
from gway_remote.mcp_link_http import Handler


class OAuthConnectScopeHTTPTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.registry = BearerRegistry(Path(self.directory.name) / "tokens.sqlite3")
        self.execute_proof = self.registry.issue(scope="gway:execute", operator_approved=True)
        self.flow = LinkFlow(self.registry, client_id="private-client",
                             redirect_uri="https://chatgpt.com/approved-callback")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.link = self.flow
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.thread.join(timeout=3)

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            conn.request(method, path, body, headers or {})
            response = conn.getresponse()
            status = response.status
            headers = dict(response.getheaders())
            content = response.read().decode("utf-8")
            return status, headers, content
        finally:
            conn.close()

    def begin(self, scope=None):
        challenge = pkce_s256("x" * 43)
        parameters = dict(client_id="private-client",
                          redirect_uri="https://chatgpt.com/approved-callback",
                          resource="https://remote.arthexis.com/mcp",
                          response_type="code", code_challenge=challenge,
                          code_challenge_method="S256", state="safe-state-123")
        if scope is not None:
            parameters["scope"] = scope
        status, headers, html = self.request("GET", "/oauth/authorize?" + urlencode(parameters))
        self.assertEqual(status, 200)
        csrf = re.search(r"name='csrf' value='([^']+)'", html).group(1)
        return headers["Set-Cookie"].split(";", 1)[0], csrf, html

    def submit(self, cookie, csrf, scope=None):
        params = {"csrf": csrf, "bearer": self.execute_proof}
        if scope is not None:
            params["scope"] = scope
        body = urlencode(params).encode()
        return self.request("POST", "/connect", body, {
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": cookie,
        })

    def test_omitted_scope_execute_choice_returns_callback(self):
        cookie, csrf, html = self.begin()
        self.assertIn("name='scope'", html)
        status, _, response = self.submit(cookie, csrf, "gway:execute")
        self.assertEqual(status, 200)
        self.assertIn("Returning to ChatGPT", response)
        self.assertEqual(len(self.flow.codes), 1)
        self.assertEqual(next(iter(self.flow.codes.values()))[3], "gway:execute")

    def test_explicit_read_scope_can_grant_execute_with_visible_consent(self):
        cookie, csrf, html = self.begin("gway:read")
        self.assertIn("Client requested: <strong>gway:read</strong>", html)
        self.assertIn("explicitly grants broader access", html)
        self.assertIn("name='scope'", html)
        status, _, response = self.submit(cookie, csrf, "gway:execute")
        self.assertEqual(status, 200)
        self.assertIn("Returning to ChatGPT", response)
        self.assertEqual(len(self.flow.codes), 1)
        self.assertEqual(next(iter(self.flow.codes.values()))[3], "gway:execute")
        self.assertNotIn(self.execute_proof, response)

    def test_mismatched_proof_returns_actionable_html_not_blank_403(self):
        cookie, csrf, _ = self.begin("gway:read")
        status, _, response = self.submit(cookie, csrf)
        self.assertEqual(status, 403)
        self.assertIn("Connection not authorized", response)
        self.assertNotIn(self.execute_proof, response)
        self.assertFalse(self.flow.codes)


if __name__ == "__main__":
    unittest.main()
