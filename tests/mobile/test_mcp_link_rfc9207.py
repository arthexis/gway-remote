"""RFC 9207 stable ChatGPT callback: exact issuer on success and OAuth errors."""
import base64
import hashlib
import http.client
import json
import re
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

    def request(self, path, method="GET", body=None, headers=None):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            client.request(method, path, body=body, headers=headers or {})
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

    def test_form_policy_allows_only_self_and_the_registered_callback_origin(self):
        for changes in ({}, {"redirect_uri": "https://attacker.invalid/return"}):
            with self.subTest(changes=changes):
                _, headers, _ = self.authorize(**changes)
                directives = dict(part.strip().split(" ", 1)
                                  for part in headers["Content-Security-Policy"].split(";"))
                self.assertEqual(directives["form-action"].split(), ["'self'", "https://chatgpt.com"])
                self.assertEqual(directives["default-src"], "'none'")
                self.assertEqual(directives["base-uri"], "'none'")
                self.assertNotIn("attacker.invalid", headers["Content-Security-Policy"])

    def test_successful_post_returns_navigable_handoff_and_repeated_submit_is_denied(self):
        import html
        status, headers, page = self.authorize()
        self.assertEqual(status, 200)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        csrf = re.search(rb"name='csrf' value='([^']+)'", page).group(1).decode()
        proof = self.registry.issue()
        body = urlencode({"csrf": csrf, "bearer": proof})
        form_headers = {"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie}
        status, headers, page = self.request("/connect", "POST", body, form_headers)
        self.assertEqual(status, 200)
        self.assertNotIn("Location", headers)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("Max-Age=0", headers["Set-Cookie"])
        self.assertIn(b"http-equiv='refresh'", page)
        self.assertIn(b"Continue to ChatGPT</a>", page)
        self.assertNotIn(proof.encode(), page)
        match = re.search(rb"href='([^']+)'", page)
        self.assertIsNotNone(match)
        target = urlsplit(html.unescape(match.group(1).decode()))
        self.assertEqual(target.scheme + "://" + target.netloc + target.path, CALLBACK)
        self.assertEqual(parse_qs(target.query)["iss"], [ISSUER])
        self.assertEqual(len(self.flow.codes), 1)
        status, headers, error = self.request("/connect", "POST", body, form_headers)
        self.assertEqual(status, 403)
        self.assertNotIn("Location", headers)
        self.assertIn(b"already submitted", error)
        self.assertNotIn(proof.encode(), error)
        self.assertEqual(len(self.flow.codes), 1)

    def test_callback_policy_cannot_include_configuration_injection(self):
        for callback in ("https://user:password@chatgpt.com/cb", "https://*.example/cb",
                         "https://chatgpt.com;form-action*/cb", "https://chatgpt.com/\r\nunsafe",
                         "https://chatgpt.com:99999/cb", "https://chatgpt.com:/cb",
                         "https://chatgpt.com/cb#fragment"):
            with self.subTest(callback=callback):
                with self.assertRaises(ValueError):
                    LinkFlow(self.registry, client_id=CLIENT, redirect_uri=callback)
        flow = LinkFlow(self.registry, client_id=CLIENT,
                        redirect_uri="https://callback.example:9443/cb?private-configuration-sentinel=1")
        self.assertEqual(flow.callback_origin, "https://callback.example:9443")

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
