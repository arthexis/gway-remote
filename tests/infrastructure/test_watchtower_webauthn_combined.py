"""C unified: real ES256, combined bearer, replay, OAuth and HTTP gates."""
import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.mcp_link import LinkFlow, RESOURCE
from gway_remote.watchtower_webauthn_admin import (
    AdminCeremonies, AdminHandler, LOOPBACK_HOST, LOOPBACK_PORT,
)
from gway_remote.watchtower_webauthn_issuer import IssuanceLedger, WatchtowerBearerIssuer
from gway_remote.watchtower_webauthn_ledger import WebAuthnLedger
from tests.infrastructure.test_watchtower_webauthn_verify import RealWebAuthnVerificationTests

BOTH = ["gway:execute", "gway:read"]


class CombinedIssuerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.ledger = WebAuthnLedger(base / "passkeys.sqlite")
        self.registry = BearerRegistry(base / "bearers.sqlite")
        self.receipts = IssuanceLedger(base / "receipts.sqlite")
        self.issuer = WatchtowerBearerIssuer(
            credentials=self.ledger, registry=self.registry, receipts=self.receipts,
            administrators={"admin"})
        self.ceremonies = AdminCeremonies(self.ledger)
        self.fido = RealWebAuthnVerificationTests(
            methodName="test_real_es256_registration_and_authentication")
        self.fido.setUp()
        self.addCleanup(self.fido.tmp.cleanup)
        grant = self.ledger.create_enrollment_grant(principal="admin")
        begin = self.ceremonies.enrollment_begin(principal="admin", grant=grant)
        self.ceremonies.enrollment_complete(
            principal="admin", challenge=begin["challenge"], ticket=begin["ticket"],
            credential=self.fido.registration(begin["challenge"]))
        self.seq = 0

    def intent(self, request_id="a" * 32, lifetime=3600):
        return {"action": "issue_mcp_bearer", "scopes": list(BOTH),
                "lifetime_seconds": lifetime, "request_id": request_id}

    def signed_issue(self, intent=None):
        self.seq += 1
        intent = intent or self.intent(request_id=format(self.seq, "032x"))
        options = self.issuer.begin_combined(principal="admin", intent=intent)
        return self.issuer.issue_combined(
            principal="admin", intent=intent, challenge=options["challenge"],
            credential=self.fido.assertion(options["challenge"], count=self.seq))

    def test_combined_verification_and_oauth_delegations(self):
        previous_read = self.registry.issue(scope="gway:read")
        previous_exec = self.registry.issue(
            scope="gway:execute", operator_approved=True)
        token = self.signed_issue()
        self.assertEqual(token["scopes"], BOTH)
        self.assertEqual(token["expires_in"], 3600)
        verifier = BearerVerifier(self.registry.path)
        for scope in BOTH:
            self.assertTrue(verifier.verify(token["bearer"], required_scope=scope))
            self.assertTrue(self.registry.verify(token["bearer"], required_scope=scope))
        self.assertTrue(verifier.verify(previous_read, required_scope="gway:read"))
        self.assertFalse(verifier.verify(previous_read, required_scope="gway:execute"))
        self.assertTrue(verifier.verify(previous_exec, required_scope="gway:execute"))
        self.assertFalse(verifier.verify(previous_exec, required_scope="gway:read"))

        # Combined parents can delegate either SINGLE requested scope, never more.
        parent_id = token["bearer_id"]
        for scope in BOTH:
            pair = self.registry.issue_oauth_pair(
                parent_id=parent_id, scope=scope, client_id="chatgpt")
            self.assertTrue(verifier.verify(pair["access_token"], required_scope=scope))
            self.assertFalse(verifier.verify(
                pair["access_token"], required_scope=(BOTH[1] if scope == BOTH[0] else BOTH[0])))
            rotated = self.registry.rotate_oauth_refresh(
                token=pair["refresh_token"], client_id="chatgpt")
            self.assertTrue(verifier.verify(rotated["access_token"], required_scope=scope))

        self.assertNotIn(token["bearer"].encode(), self.registry.path.read_bytes())
        self.assertNotIn(token["bearer"].encode(), self.receipts.path.read_bytes())
        self.assertNotIn(token["bearer"].encode(), self.ledger.path.read_bytes())

    def test_wrong_intent_and_replay_never_mint(self):
        intent = self.intent()
        options = self.issuer.begin_combined(principal="admin", intent=intent)
        altered = dict(intent, lifetime_seconds=7200)
        with self.assertRaises(ValueError):
            self.issuer.issue_combined(
                principal="admin", intent=altered, challenge=options["challenge"],
                credential=self.fido.assertion(options["challenge"]))
        # Bad intent burns original challenge; cannot retry with approved parameters.
        with self.assertRaises(ValueError):
            self.issuer.issue_combined(
                principal="admin", intent=intent, challenge=options["challenge"],
                credential=self.fido.assertion(options["challenge"]))
        self.assertFalse(self.registry.path.exists())

    def test_bad_signature_and_uv(self):
        for kwargs in ({"tamper_signature": True}, {"flags": 0x01}):
            intent = self.intent(request_id=("1" if kwargs.get("tamper_signature") else "2") * 32)
            options = self.issuer.begin_combined(principal="admin", intent=intent)
            with self.assertRaises(Exception):
                self.issuer.issue_combined(
                    principal="admin", intent=intent, challenge=options["challenge"],
                    credential=self.fido.assertion(options["challenge"], **kwargs))
            with self.assertRaises(Exception):
                self.issuer.issue_combined(
                    principal="admin", intent=intent, challenge=options["challenge"],
                    credential=self.fido.assertion(options["challenge"]))
        self.assertFalse(self.registry.path.exists())

    def test_duplicate_request_id_and_rate_limit(self):
        first = self.signed_issue(self.intent())
        with self.assertRaises(PermissionError):
            self.signed_issue(self.intent())
        self.assertTrue(self.registry.verify(first["bearer"], required_scope="gway:read"))
        self.signed_issue(self.intent(request_id="b" * 32))
        self.signed_issue(self.intent(request_id="c" * 32))
        with self.assertRaises(PermissionError):
            self.signed_issue(self.intent(request_id="d" * 32))
        with sqlite3.connect(self.registry.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM credentials").fetchone()[0], 3)

    def test_issuer_off_by_default_and_http_bound_actions(self):
        server = __import__("http.server", fromlist=["ThreadingHTTPServer"]).ThreadingHTTPServer(
            (LOOPBACK_HOST, 0), AdminHandler)
        server.ceremonies = self.ceremonies
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        self.addCleanup(t.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def post(url, value, headers=None):
            connection = http.client.HTTPConnection(LOOPBACK_HOST, server.server_port, timeout=3)
            h = {"Content-Type": "application/json",
                 "Host": "%s:%d" % (LOOPBACK_HOST, LOOPBACK_PORT)}
            h.update(headers or {})
            connection.request("POST", url, body=json.dumps(value), headers=h)
            response = connection.getresponse()
            status, content = response.status, json.loads(response.read())
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            connection.close()
            return status, content

        intent = self.intent()
        options = {"principal": "admin", "intent": intent}
        self.assertEqual(post("/v1/bearer/combined/options", options)[0], 404)
        server.issuer = self.issuer
        self.assertEqual(post("/v1/bearer/combined/options", options,
                              headers={"Origin": "https://evil.test"})[0], 403)
        self.assertEqual(post("/v1/bearer/combined/options",
                              dict(options, node="gway-001"))[0], 400)
        status, challenge = post("/v1/bearer/combined/options", options)
        self.assertEqual(status, 200)
        self.assertEqual(challenge["action"], "issue_mcp_bearer")
        payload = dict(options, challenge=challenge["challenge"],
                       credential=self.fido.assertion(challenge["challenge"]))
        status, token = post("/v1/bearer/combined/finish", payload)
        self.assertEqual(status, 200)
        self.assertTrue(self.registry.verify(token["bearer"], required_scope="gway:read"))
        self.assertTrue(self.registry.verify(token["bearer"], required_scope="gway:execute"))
        self.assertEqual(post("/v1/bearer/combined/finish", payload)[0], 403)

    def test_oauth_link_preserves_combined_permission_for_chatgpt(self):
        import base64
        import hashlib
        from urllib.parse import parse_qs, urlsplit

        parent = self.signed_issue()["bearer"]
        verifier = "v" * 43
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()).decode().rstrip("=")
        flow = LinkFlow(self.registry, client_id="chatgpt",
                        redirect_uri="https://chatgpt.com/connector_platform_oauth_redirect")
        session, _ = flow.begin(
            client_id="chatgpt", redirect_uri=flow.redirect_uri,
            resource=RESOURCE, response_type="code",
            code_challenge=challenge, code_challenge_method="S256",
            state="valid-state-12345", scope="gway:execute")
        callback = flow.connect(session, flow.pending[session][0], parent)
        code = parse_qs(urlsplit(callback).query)["code"][0]
        tokens = flow.redeem(
            client_id="chatgpt", code=code, redirect_uri=flow.redirect_uri,
            code_verifier=verifier, grant_type="authorization_code", resource=RESOURCE)
        self.assertEqual(tokens["scope"], "gway:execute gway:read")
        for scope in BOTH:
            self.assertTrue(self.registry.verify(tokens["access_token"], required_scope=scope))
        rotated = flow.refresh(
            client_id="chatgpt", refresh_token=tokens["refresh_token"],
            grant_type="refresh_token", resource=RESOURCE)
        for scope in BOTH:
            self.assertTrue(self.registry.verify(rotated["access_token"], required_scope=scope))

        legacy = self.registry.issue(scope="gway:execute", operator_approved=True)
        session, _ = flow.begin(
            client_id="chatgpt", redirect_uri=flow.redirect_uri,
            resource=RESOURCE, response_type="code",
            code_challenge=challenge, code_challenge_method="S256",
            state="valid-state-legacy", scope="gway:execute")
        callback = flow.connect(session, flow.pending[session][0], legacy)
        code = parse_qs(urlsplit(callback).query)["code"][0]
        old_tokens = flow.redeem(
            client_id="chatgpt", code=code, redirect_uri=flow.redirect_uri,
            code_verifier=verifier, grant_type="authorization_code", resource=RESOURCE)
        self.assertEqual(old_tokens["scope"], "gway:execute")
        self.assertFalse(self.registry.verify(old_tokens["access_token"],
                                              required_scope="gway:read"))

    def test_explicit_signed_revoke_is_single_use_and_bound_to_id(self):
        issued = self.signed_issue()
        intent = {"action": "revoke_mcp_bearer", "key_id": issued["bearer_id"],
                  "request_id": "f" * 32}
        options = self.issuer.begin_revoke(principal="admin", intent=intent)
        assertion = self.fido.assertion(options["challenge"], count=2)
        changed = dict(intent, key_id="a" * 24)
        with self.assertRaises(ValueError):
            self.issuer.revoke_bearer(principal="admin", intent=changed,
                                     challenge=options["challenge"], credential=assertion)
        self.assertTrue(self.registry.verify(issued["bearer"], required_scope="gway:execute"))
        with self.assertRaises(ValueError):
            self.issuer.revoke_bearer(principal="admin", intent=intent,
                                     challenge=options["challenge"], credential=assertion)
        fresh = self.issuer.begin_revoke(principal="admin", intent=intent)
        result = self.issuer.revoke_bearer(
            principal="admin", intent=intent, challenge=fresh["challenge"],
            credential=self.fido.assertion(fresh["challenge"], count=2))
        self.assertEqual(result, {"revoked": True})
        for scope in BOTH:
            self.assertFalse(self.registry.verify(issued["bearer"], required_scope=scope))
        with self.assertRaises(ValueError):
            self.issuer.revoke_bearer(
                principal="admin", intent=intent, challenge=fresh["challenge"],
                credential=self.fido.assertion(fresh["challenge"], count=3))

    def test_revoke_parent_invalidates_oauth_delegation(self):
        parent = self.signed_issue()
        pair = self.registry.issue_oauth_pair(
            parent_id=parent["bearer_id"], scope="gway:read", client_id="chatgpt")
        self.assertTrue(self.registry.verify(pair["access_token"], required_scope="gway:read"))
        self.assertTrue(self.registry.revoke(parent["bearer_id"]))
        self.assertFalse(self.registry.verify(pair["access_token"], required_scope="gway:read"))


if __name__ == "__main__":
    unittest.main()
