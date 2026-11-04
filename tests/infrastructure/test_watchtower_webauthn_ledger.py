"""Hermetic tests for B1's storage only. No authenticator claims."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.watchtower_webauthn_ledger import WebAuthnLedger, CHALLENGE_TTL


class WebAuthnLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "private" / "webauthn.sqlite"
        self.clock = [100000]
        self.store = WebAuthnLedger(self.path, now=lambda: self.clock[0])

    def begin(self, action="bearer.issue", target="gway-execute"):
        return self.store.begin(principal="admin", action=action, target=target)["challenge"]

    def consume(self, challenge, action="bearer.issue", target="gway-execute"):
        return self.store.consume(challenge=challenge, principal="admin",
                                  action=action, target=target)

    def test_challenge_is_random_bound_one_use_and_persisted(self):
        one = self.begin()
        two = self.begin()
        self.assertNotEqual(one, two)
        reopened = WebAuthnLedger(self.path, now=lambda: self.clock[0])
        self.assertTrue(reopened.consume(challenge=one, principal="admin",
                                         action="bearer.issue", target="gway-execute"))
        self.assertFalse(self.consume(one))
        self.assertTrue(self.consume(two))
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT length(challenge_hash) FROM challenges LIMIT 1").fetchone()[0], 32)
            self.assertEqual(db.execute("SELECT count(*) FROM challenges WHERE challenge_hash=?",
                                        (one.encode(),)).fetchone()[0], 0)

    def test_wrong_action_target_or_identity_burns_challenge(self):
        for override in ({"action": "secret.reveal"}, {"target": "other"},
                         {"principal": "someone_else"}):
            challenge = self.begin()
            kwargs = {"challenge": challenge, "principal": "admin",
                      "action": "bearer.issue", "target": "gway-execute"}
            kwargs.update(override)
            self.assertFalse(self.store.consume(**kwargs))
            self.assertFalse(self.consume(challenge))

    def test_expiry_and_boundary(self):
        challenge = self.begin()
        self.clock[0] += CHALLENGE_TTL
        self.assertFalse(self.consume(challenge))  # exact expiry is rejected
        self.assertFalse(self.consume(challenge))

    def test_invalid_actions_and_ids(self):
        for action in ("shell", "secret.update.all", ""):
            with self.assertRaises(ValueError):
                self.begin(action=action)
        for value in ("../root", "a/b", "", "space in id"):
            with self.assertRaises(ValueError):
                self.store.begin(principal=value, action="bearer.issue", target="test")

    def test_credential_metadata_and_revocation_are_idempotent(self):
        self.store._record_verified_credential(
            credential_id="test-key-1", principal="admin", public_key=b"X" * 65)
        self.assertEqual(self.store.credential_metadata(principal="other"), [])
        self.assertEqual(self.store.credential_metadata(principal="admin"),
                         [{"credential_id": "test-key-1", "added_at": 100000, "revoked": False}])
        self.assertTrue(self.store.revoke(credential_id="test-key-1"))
        self.assertFalse(self.store.revoke(credential_id="test-key-1"))
        self.assertTrue(self.store.credential_metadata(principal="admin")[0]["revoked"])
        with self.assertRaises(sqlite3.IntegrityError):
            self.store._record_verified_credential(
                credential_id="test-key-1", principal="admin", public_key=b"Y" * 65)

    def test_no_secret_bytes_exposed_in_metadata(self):
        self.store._record_verified_credential(
            credential_id="test", principal="admin", public_key=b"P" * 64)
        self.assertNotIn("public_key", self.store.credential_metadata(principal="admin")[0])

    def test_rejects_symlink_and_world_readable_database(self):
        other = Path(self.temp.name) / "other.db"
        other.write_bytes(b"data")
        self.path.parent.mkdir(exist_ok=True)
        self.path.symlink_to(other)
        with self.assertRaises(ValueError):
            self.begin()
        self.path.unlink()
        self.path.write_bytes(b"")
        self.path.chmod(0o644)
        with self.assertRaises(ValueError):
            self.begin()

    def test_no_authorization_or_bearer_capabilities(self):
        self.assertFalse(hasattr(self.store, "verify_assertion"))
        self.assertFalse(hasattr(self.store, "issue_bearer"))
        self.assertFalse(hasattr(self.store, "authorize"))
        self.assertFalse(hasattr(self.store, "register_passkey"))
        self.assertFalse(self.consume("unissued"))

if __name__ == "__main__":
    unittest.main()
