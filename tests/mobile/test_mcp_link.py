"""Classic-style bearer entry and authorization code one-time exchange."""
import base64
import hashlib
import tempfile
import unittest
from unittest.mock import patch
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

    def test_operator_execute_proof_links_without_per_command_approval(self):
        with tempfile.TemporaryDirectory() as d:
            registry = BearerRegistry(Path(d) / "tokens.db")
            read_proof = registry.issue()
            execute_proof = registry.issue(scope="gway:execute", operator_approved=True)
            flow = LinkFlow(registry, client_id=CLIENT, redirect_uri=URI)
            verifier = "x" * 43
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            params = dict(client_id=CLIENT, redirect_uri=URI,
                          resource="https://remote.arthexis.com/mcp",
                          response_type="code", code_challenge=challenge,
                          code_challenge_method="S256", state="execute-state-123",
                          scope="gway:execute")
            session, _ = flow.begin(**params)
            with self.assertRaisesRegex(ValueError, "^invalid_bearer$"):
                flow.connect(session, flow.pending[session][0], read_proof)
            session, _ = flow.begin(**params)
            from urllib.parse import parse_qs, urlsplit
            dest = flow.connect(session, flow.pending[session][0], execute_proof)
            code = parse_qs(urlsplit(dest).query)["code"][0]
            token = flow.redeem(client_id=CLIENT, code=code, redirect_uri=URI,
                                code_verifier=verifier, grant_type="authorization_code",
                                resource="https://remote.arthexis.com/mcp")
            self.assertEqual(token["scope"], "gway:execute")
            self.assertTrue(BearerVerifier(registry.path).verify(
                token["access_token"], required_scope="gway:execute"))
            self.assertFalse(BearerVerifier(registry.path).verify(token["access_token"]))
            self.assertEqual(BearerVerifier(registry.path).execution_principal(
                token["access_token"]), execute_proof.split("_", 2)[1])

    def test_omitted_scope_requires_explicit_operator_choice_for_execute(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = BearerRegistry(Path(directory) / "tokens.db")
            read_proof = registry.issue()
            execute_proof = registry.issue(scope="gway:execute", operator_approved=True)
            flow = LinkFlow(registry, client_id=CLIENT, redirect_uri=URI)
            verifier = "x" * 43
            challenge = base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            params = dict(client_id=CLIENT, redirect_uri=URI,
                          resource="https://remote.arthexis.com/mcp",
                          response_type="code", code_challenge=challenge,
                          code_challenge_method="S256", state="choice-state-123")
            session, page = flow.begin(**params)
            self.assertIn("name='scope'", page)
            self.assertIn("value='gway:read' checked", page)
            self.assertIn("value='gway:execute'", page)
            with self.assertRaisesRegex(ValueError, "^invalid_bearer$"):
                flow.connect(session, flow.pending[session][0], execute_proof)
            session, _ = flow.begin(**params)
            from urllib.parse import parse_qs, urlsplit
            dest = flow.connect(session, flow.pending[session][0], execute_proof,
                                selected_scope="gway:execute")
            code = parse_qs(urlsplit(dest).query)["code"][0]
            token = flow.redeem(client_id=CLIENT, code=code, redirect_uri=URI,
                                code_verifier=verifier, grant_type="authorization_code",
                                resource="https://remote.arthexis.com/mcp")
            self.assertEqual(token["scope"], "gway:execute")
            self.assertTrue(BearerVerifier(registry.path).verify(
                token["access_token"], required_scope="gway:execute"))
            self.assertFalse(BearerVerifier(registry.path).verify(token["access_token"]))
            session, _ = flow.begin(**params)
            with self.assertRaisesRegex(ValueError, "^invalid_bearer$"):
                flow.connect(session, flow.pending[session][0], read_proof,
                             selected_scope="gway:execute")

    def test_explicit_read_scope_cannot_be_upgraded_by_form_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = BearerRegistry(Path(directory) / "tokens.db")
            proof = registry.issue(scope="gway:execute", operator_approved=True)
            flow = LinkFlow(registry, client_id=CLIENT, redirect_uri=URI)
            verifier = "x" * 43
            challenge = base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            params = dict(client_id=CLIENT, redirect_uri=URI,
                          resource="https://remote.arthexis.com/mcp",
                          response_type="code", code_challenge=challenge,
                          code_challenge_method="S256", state="fixed-state-123",
                          scope="gway:read")
            session, page = flow.begin(**params)
            self.assertIn("Requested permission: <strong>gway:read</strong>", page)
            self.assertNotIn("name='scope'", page)
            with self.assertRaisesRegex(ValueError, "^scope_selection_denied$"):
                flow.connect(session, flow.pending[session][0], proof,
                             selected_scope="gway:execute")
            self.assertEqual(flow.codes, {})

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

    def test_expired_and_consumed_sessions_have_distinct_errors(self):
        with tempfile.TemporaryDirectory() as d:
            registry = BearerRegistry(Path(d) / "tokens.db")
            flow = LinkFlow(registry, client_id=CLIENT, redirect_uri=URI)
            params = dict(client_id=CLIENT, redirect_uri=URI, resource="https://remote.arthexis.com/mcp",
                          response_type="code", code_challenge="x" * 43, code_challenge_method="S256",
                          state="state-12345", scope="gway:read")
            with patch("gway_remote.mcp_link.time.monotonic", return_value=100):
                session, _ = flow.begin(**params)
            csrf = flow.pending[session][0]
            with patch("gway_remote.mcp_link.time.monotonic", return_value=401):
                with self.assertRaisesRegex(ValueError, "^expired_session$"):
                    flow.connect(session, csrf, "unused-proof")
            with self.assertRaisesRegex(ValueError, "^session_unavailable$"):
                flow.connect(session, csrf, "unused-proof")


if __name__ == "__main__":
    unittest.main()
