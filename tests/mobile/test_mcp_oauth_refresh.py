from tests.helpers.mcp_http import pkce_s256
"""OAuth refresh rotation, operator lineage and live HTTP token endpoint tests."""
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from gway_remote import mcp_link_http
from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.mcp_link import LinkFlow, RESOURCE

CLIENT = "gway-remote-private"
CALLBACK = "https://chatgpt.com/connector_platform_oauth_redirect"


class RefreshTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / "tokens.db"
        self.registry = BearerRegistry(self.db)
        self.flow = LinkFlow(self.registry, client_id=CLIENT, redirect_uri=CALLBACK)
        self.verifier = BearerVerifier(self.db)

    def grant(self, scope="gway:execute"):
        proof = self.registry.issue(scope=scope, operator_approved=scope == "gway:execute")
        challenge = pkce_s256("x" * 43)
        session, _ = self.flow.begin(
            client_id=CLIENT, redirect_uri=CALLBACK, resource=RESOURCE,
            response_type="code", code_challenge=challenge,
            code_challenge_method="S256", state="good-state-123", scope=scope)
        destination = self.flow.connect(session, self.flow.pending[session][0], proof)
        code = parse_qs(urlsplit(destination).query)["code"][0]
        result = self.flow.redeem(
            client_id=CLIENT, code=code, redirect_uri=CALLBACK,
            code_verifier="x" * 43, grant_type="authorization_code", resource=RESOURCE)
        return proof, result

    def renew(self, refresh):
        return self.flow.refresh(client_id=CLIENT, refresh_token=refresh,
                                 grant_type="refresh_token", resource=RESOURCE)

    def test_rotate_and_keep_principal_without_new_operator_approval(self):
        proof, original = self.grant()
        self.assertIn("refresh_token", original)
        self.assertEqual(original["expires_in"], 3600)
        self.assertFalse(self.verifier.verify(original["refresh_token"], required_scope="gway:execute"))
        renewed = self.renew(original["refresh_token"])
        self.assertNotEqual(renewed["access_token"], original["access_token"])
        self.assertNotEqual(renewed["refresh_token"], original["refresh_token"])
        self.assertEqual(renewed["scope"], "gway:execute")
        self.assertTrue(self.verifier.verify(renewed["access_token"], required_scope="gway:execute"))
        self.assertTrue(self.verifier.verify(original["access_token"], required_scope="gway:execute"))
        self.assertEqual(self.verifier.execution_principal(renewed["access_token"]),
                         proof.split("_", 2)[1])
        # Refresh state survives a new OAuth-link server instance.
        next_flow = LinkFlow(BearerRegistry(self.db), client_id=CLIENT, redirect_uri=CALLBACK)
        further = next_flow.refresh(client_id=CLIENT, refresh_token=renewed["refresh_token"],
                                    grant_type="refresh_token", resource=RESOURCE)
        self.assertTrue(self.verifier.verify(further["access_token"], required_scope="gway:execute"))

    def test_replay_revokes_family_but_not_independent_proof(self):
        proof, original = self.grant()
        rotated = self.renew(original["refresh_token"])
        with self.assertRaisesRegex(ValueError, "invalid_grant"):
            self.renew(original["refresh_token"])
        self.assertFalse(self.verifier.verify(rotated["access_token"], required_scope="gway:execute"))
        with self.assertRaisesRegex(ValueError, "invalid_grant"):
            self.renew(rotated["refresh_token"])
        self.assertTrue(self.verifier.verify(proof, required_scope="gway:execute"))

    def test_revocation_cascades_to_refresh_and_access(self):
        proof, original = self.grant()
        self.assertTrue(self.registry.revoke(proof.split("_", 2)[1]))
        self.assertFalse(self.verifier.verify(original["access_token"], required_scope="gway:execute"))
        with self.assertRaisesRegex(ValueError, "invalid_grant"):
            self.renew(original["refresh_token"])

    def test_read_only_scope_cannot_escalate(self):
        _, original = self.grant(scope="gway:read")
        rotated = self.renew(original["refresh_token"])
        self.assertEqual(rotated["scope"], "gway:read")
        self.assertTrue(self.verifier.verify(rotated["access_token"]))
        self.assertFalse(self.verifier.verify(rotated["access_token"], required_scope="gway:execute"))

    def test_client_resource_and_token_binding(self):
        _, original = self.grant()
        for override in ({"client_id": "attacker"}, {"resource": "https://wrong.invalid"},
                         {"grant_type": "authorization_code"}):
            with self.subTest(override=override), self.assertRaisesRegex(ValueError, "invalid_grant"):
                self.flow.refresh(**{**dict(client_id=CLIENT, resource=RESOURCE,
                    grant_type="refresh_token", refresh_token=original["refresh_token"]), **override})
        with self.assertRaisesRegex(ValueError, "invalid_grant"):
            self.renew(original["refresh_token"] + "bad")
        self.assertTrue(self.verifier.verify(self.renew(original["refresh_token"])["access_token"],
                                             required_scope="gway:execute"))

    def test_refresh_ends_with_proof_expiry(self):
        with patch("gway_remote.mcp_bearer.time.time", return_value=1000):
            proof = self.registry.issue(scope="gway:execute", lifetime=3700, operator_approved=True)
            initial = self.registry.issue_oauth_pair(
                parent_id=proof.split("_", 2)[1], scope="gway:execute", client_id=CLIENT)
        with patch("gway_remote.mcp_bearer.time.time", return_value=1050):
            renewed = self.registry.rotate_oauth_refresh(
                token=initial["refresh_token"], client_id=CLIENT)
            self.assertEqual(renewed["expires_in"], 3600)
        with patch("gway_remote.mcp_bearer.time.time", return_value=4700):
            with self.assertRaisesRegex(ValueError, "invalid_grant"):
                self.registry.rotate_oauth_refresh(token=renewed["refresh_token"], client_id=CLIENT)

    def test_legacy_access_still_valid_and_verifier_is_read_only(self):
        old = self.registry.issue()
        self.assertTrue(self.verifier.verify(old))
        self.assertFalse(hasattr(self.verifier, "issue_oauth_pair"))
        self.assertFalse(hasattr(self.verifier, "rotate_oauth_refresh"))

    def test_http_refresh_token_flow_and_metadata(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), mcp_link_http.Handler)
        server.link = self.flow
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def request(method, path, form=None):
            con = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            try:
                headers = {"Content-Type": "application/x-www-form-urlencoded"} if form else {}
                con.request(method, path, urlencode(form) if form else None, headers=headers)
                response = con.getresponse()
                return response.status, json.loads(response.read())
            finally:
                con.close()

        status, metadata = request("GET", "/.well-known/oauth-authorization-server")
        self.assertEqual(status, 200)
        self.assertIn("refresh_token", metadata["grant_types_supported"])
        _, original = self.grant()
        form = dict(client_id=CLIENT, grant_type="refresh_token", resource=RESOURCE,
                    refresh_token=original["refresh_token"])
        status, renewed = request("POST", "/oauth/token", form)
        self.assertEqual(status, 200)
        self.assertEqual(renewed["scope"], "gway:execute")
        self.assertTrue(self.verifier.verify(renewed["access_token"], required_scope="gway:execute"))
        status, denied = request("POST", "/oauth/token", {**form, "client_id": "wrong"})
        self.assertEqual((status, denied), (400, {"error": "invalid_grant"}))
        # The registered public client may omit the optional resource on refresh.
        status, next_token = request("POST", "/oauth/token", {
            "client_id": CLIENT, "grant_type": "refresh_token",
            "refresh_token": renewed["refresh_token"]})
        self.assertEqual(status, 200)
        self.assertTrue(self.verifier.verify(next_token["access_token"],
                                             required_scope="gway:execute"))
        # A replay through HTTP fails without exposing the parent credential.
        status, denied = request("POST", "/oauth/token", form)
        self.assertEqual((status, denied), (400, {"error": "invalid_grant"}))
        self.assertFalse(self.verifier.verify(renewed["access_token"], required_scope="gway:execute"))


if __name__ == "__main__":
    unittest.main()
