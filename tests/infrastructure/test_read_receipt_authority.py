"""Offline authority contract tests: no credentials, SSH, or live services."""
import hashlib
import hmac
import json
import unittest

from gway_remote.read_attestation_contract import canonical_payload
from gway_remote.read_receipt_authority import (
    ReadReceiptAuthority, ReadReceiptAuthorityUnavailable, authorize_read_receipt,
)

KEY = b"offline-only-test-key-do-not-deploy"


class ReadAuthorityContractTests(unittest.TestCase):
    def setUp(self):
        self.expected = dict(node="gway-001", address="10.90.0.2",
            host_key_sha256="a" * 64, ssh_principal="gway-read",
            identity_key_sha256="b" * 64, force_command_sha256="c" * 64)
        self.receipt = dict(schema="gway-read-attestation/v1", issuer="offline",
            key_id="test", **self.expected, issued_at=100, expires_at=200,
            serial="serial-1", signature="0" * 64)
        self.receipt["signature"] = hmac.new(
            KEY, canonical_payload(self.receipt), hashlib.sha256).hexdigest()

    def authorize(self, authority=None, receipt=None):
        return authorize_read_receipt(
            json.dumps(self.receipt if receipt is None else receipt).encode(),
            trusted_keys={("offline", "test"): KEY}, expected=self.expected,
            authority=authority, now=150)

    def test_missing_or_base_authority_fails_closed(self):
        for authority in (None, ReadReceiptAuthority()):
            with self.subTest(authority=authority), self.assertRaises(ReadReceiptAuthorityUnavailable):
                self.authorize(authority)

    def test_reject_non_authority_and_denial(self):
        with self.assertRaises(TypeError):
            self.authorize(object())

        class Deny(ReadReceiptAuthority):
            def validate_attestation(self, **kwargs):
                return False

        with self.assertRaises(ReadReceiptAuthorityUnavailable):
            self.authorize(Deny())

    def test_same_valid_receipt_can_be_revalidated(self):
        class Allow(ReadReceiptAuthority):
            def validate_attestation(self, **kwargs):
                self.last = kwargs
                return True

        authority = Allow()
        first = self.authorize(authority)
        digest = authority.last["receipt_digest"]
        self.assertEqual(self.authorize(authority), first)
        self.assertEqual(authority.last["receipt_digest"], digest)

    def test_signature_and_identity_verified_before_authority(self):
        class NeverCalled(ReadReceiptAuthority):
            def validate_attestation(self, **kwargs):
                raise AssertionError("unverified receipt reached authority")

        modified = dict(self.receipt, node="gway-002")
        with self.assertRaises(PermissionError):
            self.authorize(NeverCalled(), modified)

    def test_duplicate_json_rejected_before_authority(self):
        raw = json.dumps(self.receipt).encode()[:-1] + b', "serial": "serial-2"}'
        class NeverCalled(ReadReceiptAuthority):
            def validate_attestation(self, **kwargs):
                raise AssertionError("duplicate JSON reached authority")

        with self.assertRaises(ValueError):
            authorize_read_receipt(raw, trusted_keys={("offline", "test"): KEY},
                expected=self.expected, authority=NeverCalled(), now=150)


if __name__ == "__main__":
    unittest.main()
