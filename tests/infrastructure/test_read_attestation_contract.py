"""Offline verification; no installed keys, credentials, SSH or Watchtower."""
import hashlib
import hmac
import unittest

from gway_remote.read_attestation_contract import canonical_payload, verify_read_receipt

KEY = b"offline-test-only-secret-never-deploy!"


class ReadReceiptTests(unittest.TestCase):
    def setUp(self):
        self.claims = dict(node="gway-001", address="10.90.0.2",
            host_key_sha256="a" * 64, ssh_principal="gway-read",
            identity_key_sha256="b" * 64, force_command_sha256="c" * 64)
        self.receipt = dict(schema="gway-read-attestation/v1",
            issuer="offline-test", key_id="test-1", **self.claims,
            issued_at=100, expires_at=200, serial="receipt-001", signature="0" * 64)
        self.sign()

    def sign(self):
        self.receipt["signature"] = hmac.new(
            KEY, canonical_payload(self.receipt), hashlib.sha256).hexdigest()

    def verify(self, **kwargs):
        opts = dict(trusted_keys={("offline-test", "test-1"): KEY},
                    revoked_serials=set(), expected=self.claims, now=150)
        opts.update(kwargs)
        return verify_read_receipt(self.receipt, **opts)

    def test_verified_offline_receipt(self):
        self.assertEqual(self.verify(), self.claims)

    def test_missing_trust_anchor_and_revocation(self):
        with self.assertRaises(PermissionError):
            self.verify(trusted_keys={})
        with self.assertRaises(PermissionError):
            self.verify(revoked_serials={"receipt-001"})

    def test_expiry_future_and_invalid_signature(self):
        for now in (99, 200):
            with self.subTest(now=now), self.assertRaises(PermissionError):
                self.verify(now=now)
        self.receipt["signature"] = "0" * 64
        with self.assertRaises(PermissionError):
            self.verify()

    def test_claim_tampering_and_pinned_mismatch(self):
        for field in self.claims:
            original = self.receipt[field]
            self.receipt[field] = "d" * 64 if field.endswith("sha256") else "other"
            with self.subTest(field=field), self.assertRaises(PermissionError):
                self.verify()
            self.receipt[field] = original
        self.assertEqual(self.verify(), self.claims)

    def test_self_attested_flags_and_unsigned_fields_rejected(self):
        self.receipt["read_attested"] = True
        with self.assertRaises(ValueError):
            self.verify()
        del self.receipt["read_attested"]
        self.receipt["issuer"] = "untrusted"
        with self.assertRaises(PermissionError):
            self.verify()

    def test_missing_force_command_binding_rejected(self):
        expected = dict(self.claims)
        del expected["force_command_sha256"]
        with self.assertRaises(ValueError):
            self.verify(expected=expected)


if __name__ == "__main__":
    unittest.main()
