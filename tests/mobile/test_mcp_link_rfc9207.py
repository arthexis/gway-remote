"""RFC 9207 stable ChatGPT callback: exact issuer on success and OAuth errors."""
import base64
import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit
from http.server import ThreadingHTTPServer

from gway_remote.mcp_bearer import BearerRegistry
from gway_remote.mcp_link import ISSUER, LinkFlow, RESOURCE
from gway_remote.mcp_link_http import Handler

CALLBACK = "https://chatgpt.com/connector_platform_oauth_redirect"
CLIENT = "gway-remote-private"


class StableCallbackTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.registry = BearerRegistry(Path(temp.name) / "bearers.sqlite")
        self.flow = LinkFlow(self.registry, client_id=CLIENT, redirect_uri=CALLBACK)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.link = self.flow
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        verifier = "v" * 43
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.params = dict(client_id=CLIENT, redirect_uri=CALLBACK, resource=RESOURCE,
                           response_type="code", code_challenge=challenge,
                           code_challenge_method="S256", state="opaque-state123",
                           scope="gway:read")

    def request(self, path):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            client.request("GET", path)
            response = client.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            client.close()

    def authorize(self, **changes):
        params = {**self.params, **changes}
        return self.request("/oauth/authorize?" + urlencode(params))

    def test_discovery_advertises_issuer_and_pkce(self):
        status, _, body = self.request("/.well-known/oauth-authorization-server")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["issuer"], ISSUER)
        self.assertIs(data["authorization_response_iss_parameter_supported"], True)
        self.assertIn("S256", data["code_challenge_methods_supported"])
        status, _, body = self.request("/.well-known/oauth-protected-resource/mcp")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["authorization_servers"], [ISSUER])

    def test_success_callback_contains_exact_issuer(self):
        status, headers, _ = self.authorize()
        self.assertEqual(status, 200)
        session = headers["Set-Cookie"].split(";", 1)[0].split("=", 1)[1]
        dest = self.flow.connect(session, self.flow.pending[session][0], self.registry.issue())
        parsed = urlsplit(dest)
        self.assertEqual(f"{parsed.scheme}://{parsed.netloc}{parsed.path}", CALLBACK)
        response = parse_qs(parsed.query)
        self.assertEqual(response["iss"], [ISSUER])
        self.assertIn("code", response)
        self.assertEqual(response["state"], [self.params["state"]])

    def test_invalid_scope_redirects_to_registered_callback_with_issuer(self):
        status, headers, _ = self.authorize(scope="gway:submit")
        self.assertEqual(status, 303)
        target = headers["Location"]
        self.assertTrue(target.startswith(CALLBACK + "?"))
        params = parse_qs(urlsplit(target).query)
        self.assertEqual(params["error"], ["invalid_scope"])
        self.assertEqual(params["iss"], [ISSUER])
        self.assertEqual(params["state"], [self.params["state"]])
        self.assertNotIn("code", params)

    def test_invalid_pkce_error_has_issuer(self):
        status, headers, _ = self.authorize(code_challenge_method="plain")
        self.assertEqual(status, 303)
        self.assertEqual(parse_qs(urlsplit(headers["Location"]).query)["iss"], [ISSUER])

    def test_unregistered_client_or_redirect_never_redirects(self):
        for changed in ({"client_id": "attacker"},
                        {"redirect_uri": "https://attacker.invalid/return"},
                        {"state": ""}):
            with self.subTest(changed=changed):
                status, headers, _ = self.authorize(**changed)
                self.assertEqual(status, 400)
                self.assertNotIn("Location", headers)


if __name__ == "__main__":
    unittest.main()
