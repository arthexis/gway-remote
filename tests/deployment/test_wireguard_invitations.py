"""Offline Watchtower grant behavior, without WireGuard or network access."""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from gway_remote.wireguard_invitations import InvitationStore

NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)


class InvitationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "state" / "invitations.sqlite"

    def test_create_redeem_once_no_secret_in_metadata(self):
        with InvitationStore(self.path) as store:
            grant = store.invite("gway-004", now=NOW)
            self.assertEqual(store.redeem(grant["id"], grant["token"], now=NOW), "gway-004")
            self.assertIsNone(store.redeem(grant["id"], grant["token"], now=NOW))
            self.assertNotIn("token", store.list_metadata()[0])
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_expired_revoked_and_wrong_token(self):
        with InvitationStore(self.path) as store:
            grant = store.invite("gway-004", now=NOW)
            self.assertIsNone(store.redeem(grant["id"], "wrong", now=NOW))
            self.assertIsNone(store.redeem(grant["id"], grant["token"], now=NOW+timedelta(minutes=16)))
            self.assertTrue(store.revoke(grant["id"], now=NOW))
            self.assertIsNone(store.redeem(grant["id"], grant["token"], now=NOW))
            self.assertFalse(store.revoke(grant["id"]))

    def test_no_second_live_invitation_for_same_node(self):
        with InvitationStore(self.path) as store:
            store.invite("gway-004", now=NOW)
            with self.assertRaises(sqlite3.IntegrityError):
                store.invite("gway-004", now=NOW)
            store.invite("gway-004", now=NOW+timedelta(minutes=16))

    def test_rejects_bad_nodes_and_ttl(self):
        with InvitationStore(self.path) as store:
            for node in ("gway-001;rm", "other", "gway-abc"):
                with self.assertRaises(ValueError):
                    store.invite(node)
            for ttl in (0, 61, True):
                with self.assertRaises(ValueError):
                    store.invite("gway-004", minutes=ttl)


if __name__ == "__main__":
    unittest.main()
