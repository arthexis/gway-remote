"""Offline verification; no installed keys, credentials, SSH or Watchtower."""
import hashlib
import hmac
import json
import unittest

from gway_remote.read_attestation_contract import canonical_payload, verify_read_receipt, parse_read_receipt, MAX_RECEIPT_BYTES

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
            with self.subTest(field=field), self.assertRaises((PermissionError, ValueError)):
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

    def test_reject_noncanonical_or_public_endpoint(self):
        for field, value in (("issuer", "issuer\\u00e9"), ("serial", "a b"),
                             ("address", "8.8.8.8"), ("address", "not-an-ip"),
                             ("ssh_principal", "root;id")):
            original = self.receipt[field]
            self.receipt[field] = value
            self.sign()
            with self.subTest(field=field, value=value), self.assertRaises((ValueError, PermissionError)):
                self.verify()
            self.receipt[field] = original
        self.sign()

    def test_invalid_revocation_type_and_time_range(self):
        with self.assertRaises(PermissionError):
            self.verify(revoked_serials=["receipt-001"])
        with self.assertRaises(PermissionError):
            self.verify(revoked_serials={42})
        for issued, expires in ((200, 100), (-1, 200), (100, 100 + 86401)):
            self.receipt.update(issued_at=issued, expires_at=expires)
            self.sign()
            with self.subTest(issued=issued, expires=expires), self.assertRaises(PermissionError):
                self.verify()

    def test_expected_claims_require_string_values(self):
        expected = dict(self.claims, node=True)
        with self.assertRaises(PermissionError):
            self.verify(expected=expected)

    def test_strict_json_parser_accepts_signed_receipt(self):
        raw = json.dumps(self.receipt, sort_keys=True).encode()
        self.assertEqual(parse_read_receipt(raw), self.receipt)
        self.assertEqual(verify_read_receipt(parse_read_receipt(raw),
            trusted_keys={("offline-test", "test-1"): KEY},
            revoked_serials=set(), expected=self.claims, now=150), self.claims)

    def test_strict_json_parser_rejects_duplicate_keys(self):
        raw = json.dumps(self.receipt).encode()
        raw = raw[:-1] + b', "node": "gway-002"}'
        with self.assertRaises(ValueError):
            parse_read_receipt(raw)

    def test_strict_json_parser_rejects_invalid_input(self):
        good = json.dumps(self.receipt).encode()
        cases = (b"", b"[]", b"null", b"true", b"{", b"\\xff",
                 good + b" " * MAX_RECEIPT_BYTES, b'{"x": NaN}',
                 good.replace(b'"issued_at": 100', b'"issued_at": true'),
                 good.replace(b'"issued_at": 100', b'"issued_at": 100.0'))
        for raw in cases:
            with self.subTest(raw=raw[:60]), self.assertRaises(ValueError):
                parse_read_receipt(raw)

    def test_stateless_verifier_cannot_detect_replay(self):
        # Documents an explicit production blocker, not a replay guarantee.
        first = self.verify()
        self.assertEqual(self.verify(), first)
        with self.assertRaises(PermissionError):
            self.verify(revoked_serials={"receipt-001"})


if __name__ == "__main__":
    unittest.main()
