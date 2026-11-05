"""C3 WebAuthn bearer issuance integration, real signed ES256 assertions."""
import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.watchtower_webauthn_admin import (
    AdminCeremonies, AdminHandler, LOOPBACK_HOST, LOOPBACK_PORT,
)
from gway_remote.watchtower_webauthn_issuer import (
    IssuanceLedger, WatchtowerBearerIssuer, MAX_LIFETIME,
)
from gway_remote.watchtower_webauthn_ledger import WebAuthnLedger
from tests.infrastructure.test_watchtower_webauthn_verify import RealWebAuthnVerificationTests


class IssuerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.clock = [100000]
        self.ledger = WebAuthnLedger(root / "passkeys.sqlite", now=lambda: self.clock[0])
        self.registry = BearerRegistry(root / "bearers.sqlite")
        self.receipts = IssuanceLedger(root / "receipts.sqlite", now=lambda: self.clock[0])
        self.issuer = WatchtowerBearerIssuer(
            credentials=self.ledger, registry=self.registry,
            receipts=self.receipts, administrators={"admin"})
        self.ceremonies = AdminCeremonies(self.ledger)
        self.fido = RealWebAuthnVerificationTests(
            methodName="test_real_es256_registration_and_authentication")
        self.fido.setUp()
        self.addCleanup(self.fido.tmp.cleanup)
        grant = self.ledger.create_enrollment_grant(principal="admin")
        enrollment = self.ceremonies.enrollment_begin(principal="admin", grant=grant)
        self.ceremonies.enrollment_complete(
            principal="admin", challenge=enrollment["challenge"],
            ticket=enrollment["ticket"],
            credential=self.fido.registration(enrollment["challenge"]))
        self.counter = 0

    def request(self, *, scope="gway:execute"):
        return self.ceremonies.assertion_begin(
            principal="admin", action="bearer.issue",
            target="gway-execute" if scope == "gway:execute" else "gway-read")

    def issue(self, *, scope="gway:execute", lifetime=3600, assertion_kwargs=None):
        self.counter += 1
        issued = self.request(scope=scope)
        return self.issuer.issue(
            principal="admin", scope=scope, lifetime=lifetime,
            challenge=issued["challenge"],
            credential=self.fido.assertion(
                issued["challenge"], count=self.counter,
                **(assertion_kwargs or {})))

    def receipt_count(self):
        with sqlite3.connect(self.receipts.path) as db:
            return db.execute("SELECT count(*) FROM receipts").fetchone()[0]

    def credential_count(self):
        with sqlite3.connect(self.registry.path) as db:
            return db.execute("SELECT count(*) FROM credentials").fetchone()[0]

    def test_real_signed_issuer_and_legacy_bearer_survives(self):
        old = self.registry.issue(scope="gway:execute", operator_approved=True)
        result = self.issue()
        self.assertTrue(result["bearer"].startswith("gwr_"))
        self.assertEqual(result["scope"], "gway:execute")
        self.assertEqual(result["expires_in"], 3600)
        self.assertTrue(BearerVerifier(self.registry.path).verify(
            result["bearer"], required_scope="gway:execute"))
        self.assertTrue(self.registry.verify(old, required_scope="gway:execute"))
        self.assertEqual(self.credential_count(), 2)
        self.assertEqual(self.receipt_count(), 1)
        for path in (self.ledger.path, self.receipts.path, self.registry.path):
            self.assertNotIn(result["bearer"].encode(), path.read_bytes())
        with sqlite3.connect(self.receipts.path) as db:
            row = db.execute("SELECT principal,scope,bearer_id FROM receipts").fetchone()
            self.assertEqual(row, ("admin", "gway:execute", result["bearer_id"]))

    def test_one_token_read_scope_is_not_execute(self):
        token = self.issue(scope="gway:read")["bearer"]
        self.assertTrue(self.registry.verify(token, required_scope="gway:read"))
        self.assertFalse(self.registry.verify(token, required_scope="gway:execute"))

    def test_replay_and_altered_signature_do_not_mint(self):
        challenge = self.request()["challenge"]
        invalid = self.fido.assertion(challenge, count=1, tamper_signature=True)
        with self.assertRaises(Exception):
            self.issuer.issue(principal="admin", scope="gway:execute",
                              lifetime=3600, challenge=challenge, credential=invalid)
        with self.assertRaises(Exception):
            self.issuer.issue(principal="admin", scope="gway:execute",
                              lifetime=3600, challenge=challenge,
                              credential=self.fido.assertion(challenge, count=1))
        self.assertEqual(self.receipt_count() if self.receipts.path.exists() else 0, 0)
        self.assertFalse(self.registry.path.exists())

    def test_wrong_target_scope_admin_and_lifetime_fail_closed(self):
        with self.assertRaises(ValueError):
            WatchtowerBearerIssuer(credentials=self.ledger, registry=self.registry,
                                   receipts=self.receipts, administrators=set())
        challenge = self.request(scope="gway:read")["challenge"]
        with self.assertRaises(ValueError):
            self.issuer.issue(principal="admin", scope="gway:execute",
                              lifetime=3600, challenge=challenge,
                              credential=self.fido.assertion(challenge))
        with self.assertRaises(PermissionError):
            self.issuer.issue(principal="outsider", scope="gway:execute",
                              lifetime=3600, challenge=challenge,
                              credential=self.fido.assertion(challenge))
        for length in (0, 59, -1, MAX_LIFETIME + 1, True, "3600"):
            with self.assertRaises(ValueError):
                self.issuer.issue(principal="admin", scope="gway:execute",
                                  lifetime=length, challenge=challenge,
                                  credential=self.fido.assertion(challenge))
        self.assertFalse(self.registry.path.exists())

    def test_rate_limit_is_persistent_across_issuer_instances(self):
        for _ in range(3):
            self.issue()
        rebuilt = WatchtowerBearerIssuer(
            credentials=self.ledger, registry=self.registry,
            receipts=IssuanceLedger(self.receipts.path, now=lambda: self.clock[0]),
            administrators={"admin"})
        challenge = self.request()["challenge"]
        with self.assertRaises(PermissionError):
            rebuilt.issue(principal="admin", scope="gway:execute",
                          lifetime=3600, challenge=challenge,
                          credential=self.fido.assertion(challenge, count=4))
        self.assertEqual(self.receipt_count(), 3)
        self.assertEqual(self.credential_count(), 3)

    def test_revocation_blocks_issuance(self):
        self.ledger.revoke(credential_id=self.fido.cid)
        challenge = self.request()["challenge"]
        with self.assertRaises(ValueError):
            self.issuer.issue(principal="admin", scope="gway:execute",
                              lifetime=3600, challenge=challenge,
                              credential=self.fido.assertion(challenge))
        self.assertFalse(self.registry.path.exists())

    def test_http_issuer_disabled_by_default_and_one_time_when_injected(self):
        server = ThreadingHTTPServer((LOOPBACK_HOST, 0), AdminHandler)
        server.ceremonies = self.ceremonies
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def post(data, origin=None):
            client = http.client.HTTPConnection(LOOPBACK_HOST, server.server_port, timeout=3)
            headers = {"Host": "%s:%d" % (LOOPBACK_HOST, LOOPBACK_PORT),
                       "Content-Type": "application/json"}
            if origin is not None:
                headers["Origin"] = origin
            client.request("POST", "/v1/bearer/issue", json.dumps(data), headers=headers)
            response = client.getresponse()
            result = json.loads(response.read().decode())
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            client.close()
            return response.status, result

        challenge = self.request()["challenge"]
        body = {"principal": "admin", "scope": "gway:execute", "lifetime": 3600,
                "challenge": challenge,
                "credential": self.fido.assertion(challenge, count=1)}
        self.assertEqual(post(body)[0], 404)
        server.issuer = self.issuer
        self.assertEqual(post(body, origin="https://evil.example")[0], 403)
        # The older single-scope issuer did NOT bind lifetime to the challenge;
        # never expose that method over HTTP, even with an issuer injected.
        self.assertEqual(post({**body, "unexpected": "value"})[0], 404)
        self.assertEqual(post(body)[0], 404)
        self.assertFalse(self.registry.path.exists())


if __name__ == "__main__":
    unittest.main()
