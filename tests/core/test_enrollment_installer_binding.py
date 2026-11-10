"""Read-only enrollment installer binding must not accept stale or spoofed identities."""
import sqlite3
from pathlib import Path
import tempfile
import unittest

from gway_remote.node_registry_inventory import _installer_bindings


class EnrollmentInstallerBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "ledger.sqlite3"
        with sqlite3.connect(self.db) as db:
            db.execute("""CREATE TABLE installer_identity_bindings (
                device TEXT, host_public_key TEXT, unix_user TEXT, state TEXT
            )""")

    def insert(self, node="gway-001", key="hostkey", user="installer", state="active"):
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO installer_identity_bindings VALUES (?,?,?,?)",
                       (node, key, user, state))

    def test_missing_binding_denied(self):
        self.assertEqual(_installer_bindings(self.db), {})

    def test_active_binding_is_read_only(self):
        self.insert()
        self.assertEqual(_installer_bindings(self.db)["gway-001"],
                         ("hostkey", "installer"))

    def test_invalid_or_revoked_binding_denied(self):
        for user, state in (("root", "active"), ("evil;id", "active"),
                            ("installer", "revoked"), ("", "active")):
            with self.subTest(user=user, state=state):
                with sqlite3.connect(self.db) as db:
                    db.execute("DELETE FROM installer_identity_bindings")
                self.insert(user=user, state=state)
                self.assertNotIn("gway-001", _installer_bindings(self.db))

    def test_ambiguous_rotation_fails_closed(self):
        self.insert()
        self.insert(key="rotated", user="other")
        self.assertIsNone(_installer_bindings(self.db)["gway-001"])

    def test_no_table_fails_closed(self):
        with sqlite3.connect(self.db) as db:
            db.execute("DROP TABLE installer_identity_bindings")
        self.assertEqual(_installer_bindings(self.db), {})


if __name__ == "__main__":
    unittest.main()
