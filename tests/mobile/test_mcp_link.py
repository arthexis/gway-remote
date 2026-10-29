"""Classic-style bearer entry and authorization code one-time exchange."""
import base64
import hashlib
import tempfile
import unittest
from pathlib import Path
from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.mcp_link import LinkFlow

URI = "https://chatgpt.com/connector_platform_oauth_redirect"
CLIENT = "gway-remote-private"


class LinkFlowTests(unittest.TestCase):
    def test_bearer_link_pkce_one_time_code(self):
        with tempfile.TemporaryDirectory() as d:
            registry = BearerRegistry(Path(d) / "tokens.db")
            console_bearer = registry.issue()
            flow = LinkFlow(registry, client_id=CLIENT, redirect_uri=URI)
            verifier = "x" * 43
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            params = dict(client_id=CLIENT, redirect_uri=URI,
                          resource="https://remote.arthexis.com/mcp",
                          response_type="code", code_challenge=challenge,
                          code_challenge_method="S256", state="safe-state-123",
                          scope="gway:read")
            session, page = flow.begin(**params)
            self.assertIn('type=\'password\'', page)
            self.assertNotIn(console_bearer, page)
            csrf = flow.pending[session][0]
            with self.assertRaises(ValueError):
                flow.connect(session, "wrong-csrf", console_bearer)
            session, _ = flow.begin(**params)
            csrf = flow.pending[session][0]
            dest = flow.connect(session, csrf, console_bearer)
            from urllib.parse import parse_qs, urlsplit
            code = parse_qs(urlsplit(dest).query)["code"][0]
            exchange = dict(client_id=CLIENT, code=code, redirect_uri=URI,
                            code_verifier=verifier, grant_type="authorization_code",
                            resource="https://remote.arthexis.com/mcp")
            with self.assertRaises(ValueError):
                flow.redeem(**{**exchange, "code_verifier":"z"*43})
            with self.assertRaises(ValueError):
                flow.redeem(**exchange)
            session, _ = flow.begin(**params)
            dest = flow.connect(session, flow.pending[session][0], console_bearer)
            exchange["code"] = parse_qs(urlsplit(dest).query)["code"][0]
            access = flow.redeem(**exchange)["access_token"]
            self.assertTrue(BearerVerifier(registry.path).verify(access))
            self.assertNotEqual(access, console_bearer)
            self.assertFalse(hasattr(BearerVerifier(registry.path), "issue"))
            with self.assertRaises(ValueError):
                flow.redeem(**exchange)

    def test_rejects_unapproved_redirect_and_scope(self):
        with tempfile.TemporaryDirectory() as d:
            flow = LinkFlow(BearerRegistry(Path(d) / "tokens.db"), client_id=CLIENT, redirect_uri=URI)
            params = dict(client_id=CLIENT, redirect_uri=URI, resource="https://remote.arthexis.com/mcp",
                          response_type="code", code_challenge="x"*43, code_challenge_method="S256",
                          state="state-12345", scope="gway:read")
            for change in ({"redirect_uri":"https://evil.invalid/cb"}, {"scope":"gway:submit"},
                           {"code_challenge_method":"plain"}):
                with self.assertRaises(ValueError):
                    flow.begin(**{**params, **change})


if __name__ == "__main__":
    unittest.main()
