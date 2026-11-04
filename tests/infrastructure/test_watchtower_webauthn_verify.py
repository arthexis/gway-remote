"""Real ES256 WebAuthn ceremonies; no mocked success verifier."""
import base64
import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

# Discovery runs across all test groups without the isolated B2 dependency.
# Tests still FAIL if executed without the actual cryptographic library.
try:
    import cbor2
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
except ImportError:
    cbor2 = hashes = ec = None

from gway_remote.watchtower_webauthn_ledger import WebAuthnLedger
from gway_remote.watchtower_webauthn_verify import (
    verify_assertion, verify_registration, RP_ID, ORIGIN,
)


def b64(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def client_data(kind, challenge, origin=ORIGIN):
    return json.dumps({"type": kind, "challenge": challenge, "origin": origin,
                       "crossOrigin": False}, separators=(",", ":")).encode()


class RealWebAuthnVerificationTests(unittest.TestCase):
    def setUp(self):
        if cbor2 is None or hashes is None or ec is None:
            raise RuntimeError("B2 verifier dependencies are required for actual tests")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = [100000]
        self.ledger = WebAuthnLedger(Path(self.tmp.name) / "web.sqlite",
                                    now=lambda: self.clock[0])
        self.private = ec.generate_private_key(ec.SECP256R1())
        pub = self.private.public_key().public_numbers()
        self.cose = cbor2.dumps({1: 2, 3: -7, -1: 1,
                                -2: pub.x.to_bytes(32, "big"),
                                -3: pub.y.to_bytes(32, "big")})
        self.raw_id = b"test-credential-unique-id-1234"
        self.cid = b64(self.raw_id)

    def begin(self, action, target):
        return self.ledger.begin(principal="admin", action=action, target=target)["challenge"]

    def registration(self, challenge, *, origin=ORIGIN, rp_id=RP_ID, flags=0x45):
        # UP, UV, AT; authenticator data contains attested credential data.
        auth_data = (hashlib.sha256(rp_id.encode()).digest() + bytes([flags]) +
                     struct.pack(">I", 0) + bytes(16) +
                     struct.pack(">H", len(self.raw_id)) + self.raw_id + self.cose)
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {"id": self.cid, "rawId": self.cid, "type": "public-key",
                "response": {"attestationObject": b64(att),
                             "clientDataJSON": b64(client_data("webauthn.create", challenge, origin))}}

    def assertion(self, challenge, *, origin=ORIGIN, rp_id=RP_ID, flags=0x05,
                  count=1, tamper_signature=False):
        auth_data = hashlib.sha256(rp_id.encode()).digest() + bytes([flags]) + struct.pack(">I", count)
        client = client_data("webauthn.get", challenge, origin)
        signature = self.private.sign(auth_data + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        if tamper_signature:
            signature = signature[:-1] + bytes([signature[-1] ^ 1])
        return {"id": self.cid, "rawId": self.cid, "type": "public-key",
                "response": {"authenticatorData": b64(auth_data),
                             "clientDataJSON": b64(client), "signature": b64(signature)}}

    def enroll_fictitious(self):
        challenge = self.begin("passkey.enroll", "admin")
        result = verify_registration(self.ledger, challenge=challenge, principal="admin",
                                     credential=self.registration(challenge))
        self.assertEqual(result.credential_id, self.cid)
        # B2 has no self-enrollment: fixture explicitly inserts verified result
        # through a private persistence sink to exercise assertion verification.
        self.ledger._record_verified_credential(
            credential_id=result.credential_id, principal="admin",
            public_key=result.public_key)
        return result

    def test_real_es256_registration_and_authentication(self):
        self.enroll_fictitious()
        challenge = self.begin("bearer.issue", "gway-execute")
        verified = verify_assertion(
            self.ledger, challenge=challenge, principal="admin", action="bearer.issue",
            target="gway-execute", credential=self.assertion(challenge))
        self.assertEqual(verified.credential_id, self.cid)
        self.assertEqual(verified.sign_count, 1)
        with self.assertRaises(ValueError):
            verify_assertion(self.ledger, challenge=challenge, principal="admin",
                             action="bearer.issue", target="gway-execute",
                             credential=self.assertion(challenge, count=2))

    def test_bad_registration_origin_rp_id_uv_and_challenge(self):
        for kwargs in ({"origin": "https://evil.example"}, {"rp_id": "evil.example"},
                       {"flags": 0x41}):
            challenge = self.begin("passkey.enroll", "admin")
            with self.assertRaises(Exception):
                verify_registration(self.ledger, challenge=challenge, principal="admin",
                                    credential=self.registration(challenge, **kwargs))
            with self.assertRaises(ValueError):
                verify_registration(self.ledger, challenge=challenge, principal="admin",
                                    credential=self.registration(challenge))
        challenge = self.begin("passkey.enroll", "admin")
        with self.assertRaises(Exception):
            verify_registration(self.ledger, challenge=challenge, principal="admin",
                                credential=self.registration("not-"+challenge))
        self.assertEqual(self.ledger.credential_metadata(principal="admin"), [])

    def test_bad_authentication_origin_rp_uv_signature_and_counter(self):
        self.enroll_fictitious()
        for kwargs in ({"origin": "https://evil.example"}, {"rp_id": "evil.example"},
                       {"flags": 0x01}, {"tamper_signature": True}):
            challenge = self.begin("bearer.issue", "gway-execute")
            with self.assertRaises(Exception):
                verify_assertion(self.ledger, challenge=challenge, principal="admin",
                                 action="bearer.issue", target="gway-execute",
                                 credential=self.assertion(challenge, **kwargs))
            with self.assertRaises(ValueError):
                verify_assertion(self.ledger, challenge=challenge, principal="admin",
                                 action="bearer.issue", target="gway-execute",
                                 credential=self.assertion(challenge))
        good = self.begin("bearer.issue", "gway-execute")
        verify_assertion(self.ledger, challenge=good, principal="admin", action="bearer.issue",
                         target="gway-execute", credential=self.assertion(good, count=4))
        rollback = self.begin("bearer.issue", "gway-execute")
        with self.assertRaises(Exception):
            verify_assertion(self.ledger, challenge=rollback, principal="admin",
                             action="bearer.issue", target="gway-execute",
                             credential=self.assertion(rollback, count=3))

    def test_revoked_unknown_and_principal_mismatch(self):
        self.enroll_fictitious()
        challenge = self.begin("bearer.issue", "gway-execute")
        with self.assertRaises(ValueError):
            verify_assertion(self.ledger, challenge=challenge, principal="admin",
                             action="bearer.issue", target="other",
                             credential=self.assertion(challenge))
        self.ledger.revoke(credential_id=self.cid)
        challenge = self.begin("secret.reveal", "test-secret")
        with self.assertRaises(ValueError):
            verify_assertion(self.ledger, challenge=challenge, principal="admin",
                             action="secret.reveal", target="test-secret",
                             credential=self.assertion(challenge))
        self.assertIsNone(self.ledger._verified_credential(credential_id=self.cid,
                                                           principal="admin"))

    def test_registration_never_persists_without_admin_bootstrap(self):
        challenge = self.begin("passkey.enroll", "admin")
        proof = verify_registration(self.ledger, challenge=challenge, principal="admin",
                                    credential=self.registration(challenge))
        self.assertEqual(proof.credential_id, self.cid)
        self.assertEqual(self.ledger.credential_metadata(principal="admin"), [])


if __name__ == "__main__":
    unittest.main()
