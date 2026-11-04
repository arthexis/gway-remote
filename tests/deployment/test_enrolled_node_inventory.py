"""Single-source enrollment inventory contracts: Ansible and MCP are projections."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from gway_remote import node_registry_inventory as nodes
from gway_remote.watchtower_exec_eligibility import set_eligibility


class NodeRegistryInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.ledger = self.base / "ledger.sqlite3"
        with sqlite3.connect(self.ledger) as db:
            db.executescript("""
                CREATE TABLE devices (device TEXT PRIMARY KEY, public_key TEXT, address TEXT, state TEXT);
                CREATE TABLE host_identities (device TEXT, wireguard_identity TEXT, host_public_key TEXT,
                  enrollment_binding TEXT, state TEXT, created_at TEXT, valid_until TEXT);
                CREATE TABLE host_identity_rotations (device TEXT, previous_host_public_key TEXT,
                  next_host_public_key TEXT, created_at TEXT, state TEXT);
            """)
            db.executemany("INSERT INTO devices VALUES (?,?,?,?)", [
                ("gway-001", "wg-one", "10.90.0.2/32", "active"),
                ("gway-002", "wg-two", "10.90.0.3/32", "active"),
                ("gway-003", "wg-three", "10.90.0.4/32", "revoked"),
                ("evil-name", "wg-four", "10.90.0.5/32", "active"),
            ])
            now = datetime.now(timezone.utc)
            db.execute("INSERT INTO host_identities VALUES (?,?,?,?,?,?,?)",
                       ("gway-001", "wg-one", "ssh-ed25519 pinned-key",
                        "binding", "active", now.isoformat(),
                        (now + timedelta(days=60)).isoformat()))
            db.execute("INSERT INTO host_identities VALUES (?,?,?,?,?,?,?)",
                       ("gway-002", "other-wireguard-key", "ssh-ed25519 wrong",
                        "binding", "active", now.isoformat(),
                        (now + timedelta(days=60)).isoformat()))

    def test_only_enrolled_active_nodes_appear_and_identity_is_verified_separately(self):
        result = nodes.build(self.ledger)
        self.assertEqual(result["source"], "watchtower-enrollment-ledger")
        self.assertEqual([x["node"] for x in result["nodes"]], ["gway-001", "gway-002"])
        self.assertTrue(result["nodes"][0]["identity_verified"])
        self.assertFalse(result["nodes"][1]["identity_verified"])
        self.assertEqual([x["reachable"] for x in result["nodes"]], ["unknown", "unknown"])
        self.assertFalse(any(x["execute_available"] for x in result["nodes"]))

    def test_snapshot_is_projection_for_both_interfaces(self):
        record = nodes.build(self.ledger)
        file = self.base / "snapshot.json"
        file.write_text(json.dumps(record))
        original = nodes.load
        with patch.object(nodes, "load", side_effect=lambda path=nodes.SNAPSHOT, require_owner=True:
                          original(file, require_owner=False)):
            ansible = nodes.ansible_inventory()
            mcp = nodes.public_nodes()
            self.assertEqual(ansible["gway_enrolled"]["hosts"],
                             [x["node"] for x in mcp["nodes"]])
            self.assertEqual(ansible["_meta"]["hostvars"]["gway-001"]["gway_management_address"],
                             "10.90.0.2")
            self.assertNotIn("remote_managed_repositories",
                             ansible["_meta"]["hostvars"]["gway-001"])
            self.assertNotIn("address", mcp["nodes"][0])
            self.assertNotIn("host_public_key", json.dumps(mcp))
            self.assertFalse(nodes.capabilities("gway-001")["execute_available"])
            with self.assertRaises(ValueError):
                nodes.capabilities("gway-999")

    def test_central_eligibility_grant_and_revoke_are_projected(self):
        from unittest.mock import patch
        with patch("gway_remote.watchtower_exec_eligibility.os.geteuid", return_value=0):
            set_eligibility("gway-001", True, ledger=self.ledger)
            active = nodes.build(self.ledger)
            self.assertTrue(active["nodes"][0]["execute_eligible"])
            self.assertFalse(active["nodes"][1]["execute_eligible"])
            with self.assertRaises(PermissionError):
                set_eligibility("gway-003", True, ledger=self.ledger)
            set_eligibility("gway-001", False, ledger=self.ledger)
            self.assertFalse(nodes.build(self.ledger)["nodes"][0]["execute_eligible"])

    def test_non_root_cannot_issue_eligibility_grants(self):
        with patch("gway_remote.watchtower_exec_eligibility.os.geteuid", return_value=1000):
            with self.assertRaises(PermissionError):
                set_eligibility("gway-001", True, ledger=self.ledger)

    def test_stale_snapshot_fails_closed(self):
        snapshot = nodes.build(self.ledger)
        snapshot["generated_at"] = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
        path = self.base / "stale.json"
        path.write_text(json.dumps(snapshot))
        with self.assertRaisesRegex(ValueError, "stale"):
            nodes.load(path, require_owner=False)

    def test_untrusted_and_symlink_snapshots_rejected(self):
        snapshot = self.base / "snapshot.json"
        snapshot.write_text(json.dumps(nodes.build(self.ledger)))
        with self.assertRaisesRegex(ValueError, "untrusted"):
            nodes.load(snapshot)
        link = self.base / "alias"
        link.symlink_to(snapshot)
        with self.assertRaisesRegex(ValueError, "unsafe"):
            nodes.load(link, require_owner=False)

    def test_export_is_not_available_to_unprivileged_callers(self):
        with patch.object(nodes.os, "geteuid", return_value=1000):
            with self.assertRaisesRegex(ValueError, "root"):
                nodes.publish(nodes.build(self.ledger))


if __name__ == "__main__":
    unittest.main()
