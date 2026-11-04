"""C1/C2 admin enrollment and actual WebAuthn ceremony integration tests."""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from gway_remote.watchtower_webauthn_ledger import WebAuthnLedger, ENROLLMENT_GRANT_TTL
from gway_remote.watchtower_webauthn_admin import (
    AdminCeremonies, AdminHandler, LOOPBACK_HOST, LOOPBACK_PORT,
)
from http.server import ThreadingHTTPServer

from tests.infrastructure.test_watchtower_webauthn_verify import RealWebAuthnVerificationTests


class AdminWebAuthnTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = [100000]
        self.ledger = WebAuthnLedger(Path(self.tmp.name) / "admin.sqlite",
                                    now=lambda: self.now[0])
        self.admin = AdminCeremonies(self.ledger)
        self.fido = RealWebAuthnVerificationTests(methodName="test_real_es256_registration_and_authentication")
        self.fido.setUp()
        self.addCleanup(self.fido.tmp.cleanup)

    def test_operator_grant_enrolls_real_fido_proof_once(self):
        grant = self.ledger.create_enrollment_grant(principal="admin")
        pending = self.admin.enrollment_begin(principal="admin", grant=grant)
        self.assertNotIn(grant, str(pending))
        self.assertNotIn(grant.encode(), self.ledger.path.read_bytes())
        with self.assertRaises(ValueError):
            self.admin.enrollment_begin(principal="admin", grant=grant)
        response = self.admin.enrollment_complete(
            principal="admin", challenge=pending["challenge"],
            ticket=pending["ticket"], credential=self.fido.registration(pending["challenge"]))
        self.assertEqual(response, {"registered": True})
        self.assertEqual(len(self.ledger.credential_metadata(principal="admin")), 1)
        with self.assertRaises(ValueError):
            self.admin.enrollment_complete(
                principal="admin", challenge=pending["challenge"],
                ticket=pending["ticket"], credential=self.fido.registration(pending["challenge"]))
        assertion = self.admin.assertion_begin(principal="admin", action="bearer.issue",
                                              target="gway-execute")
        verified = self.admin.assertion_complete(
            principal="admin", action="bearer.issue", target="gway-execute",
            challenge=assertion["challenge"],
            credential=self.fido.assertion(assertion["challenge"]))
        self.assertEqual(verified, {"verified": True})
        self.assertFalse(hasattr(self.admin, "issue_bearer"))

    def test_wrong_grant_identity_expiry_and_ticket_mismatch(self):
        grant = self.ledger.create_enrollment_grant(principal="admin")
        with self.assertRaises(ValueError):
            self.admin.enrollment_begin(principal="someone", grant=grant)
        self.now[0] += ENROLLMENT_GRANT_TTL
        with self.assertRaises(ValueError):
            self.admin.enrollment_begin(principal="admin", grant=grant)
        grant = self.ledger.create_enrollment_grant(principal="admin")
        pending = self.admin.enrollment_begin(principal="admin", grant=grant)
        with self.assertRaises(ValueError):
            self.admin.enrollment_complete(
                principal="admin", challenge="X" * 43, ticket=pending["ticket"],
                credential=self.fido.registration(pending["challenge"]))
        with self.assertRaises(ValueError):
            self.admin.enrollment_complete(
                principal="admin", challenge=pending["challenge"], ticket=pending["ticket"],
                credential=self.fido.registration(pending["challenge"]))
        self.assertEqual(self.ledger.credential_metadata(principal="admin"), [])

    def test_enrollment_ticket_expires_before_completion(self):
        grant = self.ledger.create_enrollment_grant(principal="admin")
        pending = self.admin.enrollment_begin(principal="admin", grant=grant)
        self.now[0] = pending["expires_at"]
        with self.assertRaises(ValueError):
            self.admin.enrollment_complete(
                principal="admin", challenge=pending["challenge"],
                ticket=pending["ticket"],
                credential=self.fido.registration(pending["challenge"]))
        self.assertEqual(self.ledger.credential_metadata(principal="admin"), [])

    def test_bad_attestation_burns_enrollment_once(self):
        grant = self.ledger.create_enrollment_grant(principal="admin")
        pending = self.admin.enrollment_begin(principal="admin", grant=grant)
        with self.assertRaises(Exception):
            self.admin.enrollment_complete(
                principal="admin", challenge=pending["challenge"],
                ticket=pending["ticket"],
                credential=self.fido.registration(pending["challenge"],
                                                  origin="https://evil.example"))
        self.assertEqual(self.ledger.credential_metadata(principal="admin"), [])
        with self.assertRaises(ValueError):
            self.admin.enrollment_complete(
                principal="admin", challenge=pending["challenge"],
                ticket=pending["ticket"],
                credential=self.fido.registration(pending["challenge"]))

    def test_revocation_blocks_real_signed_assertions(self):
        grant = self.ledger.create_enrollment_grant(principal="admin")
        pending = self.admin.enrollment_begin(principal="admin", grant=grant)
        self.admin.enrollment_complete(
            principal="admin", challenge=pending["challenge"],
            ticket=pending["ticket"], credential=self.fido.registration(pending["challenge"]))
        assert self.ledger.revoke(credential_id=self.fido.cid)
        challenge = self.admin.assertion_begin(
            principal="admin", action="bearer.issue", target="gway-execute")
        with self.assertRaises(ValueError):
            self.admin.assertion_complete(
                principal="admin", action="bearer.issue", target="gway-execute",
                challenge=challenge["challenge"],
                credential=self.fido.assertion(challenge["challenge"]))

    def test_loopback_http_rejects_bad_host_origin_and_unlisted_routes(self):
        server = ThreadingHTTPServer((LOOPBACK_HOST, 0), AdminHandler)
        server.ceremonies = self.admin
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def post(path, payload, host=None, origin=None):
            c = http.client.HTTPConnection(LOOPBACK_HOST, server.server_port, timeout=3)
            headers = {"Content-Type": "application/json",
                       "Host": host or "%s:%d" % (LOOPBACK_HOST, LOOPBACK_PORT)}
            if origin is not None:
                headers["Origin"] = origin
            c.request("POST", path, body=json.dumps(payload), headers=headers)
            res = c.getresponse()
            body = res.read().decode()
            self.assertEqual(res.getheader("Cache-Control"), "no-store")
            c.close()
            return res.status, json.loads(body)

        grant = self.ledger.create_enrollment_grant(principal="admin")
        data = {"principal": "admin", "grant": grant}
        self.assertEqual(post("/v1/enrollment/begin", data, host="evil.local")[0], 403)
        self.assertEqual(post("/v1/enrollment/begin", data,
                              origin="https://evil.example")[0], 403)
        self.assertEqual(post("/v1/bearer/issue", data)[0], 404)
        self.assertEqual(post("/v1/enrollment/begin", {**data, "unknown": 1})[0], 400)
        status, response = post("/v1/enrollment/begin", data)
        self.assertEqual(status, 200)
        self.assertIn("ticket", response)
        self.assertNotIn(grant, json.dumps(response))
        self.assertEqual(post("/v1/enrollment/begin", data)[0], 403)


if __name__ == "__main__":
    unittest.main()
