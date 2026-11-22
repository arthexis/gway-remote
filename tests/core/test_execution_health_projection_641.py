"""Execution health is fresh authenticated evidence, not eligibility."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from gway_remote.execution_health import MAX_AGE_SECONDS, project_health, recent_probes
from gway_remote.mcp_bearer_gateway import local_node_result
from gway_remote.mcp_bridge_session import SessionBridgeDispatch

NODE = "gway-002"
KEY = "a" * 64


class ExecutionHealthTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "requests.sqlite3"
        self.path.parent.chmod(0o700)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE requests (node TEXT, host_key_sha256 TEXT, "
                       "command TEXT, state TEXT, updated_at TEXT)")
        self.path.chmod(0o600)
        self.now = datetime.now(timezone.utc)
        pinned = SimpleNamespace(node=NODE, host_key_sha256=KEY)
        self.execution = SimpleNamespace(
            enabled=True, ledger=SimpleNamespace(path=self.path),
            relay=SimpleNamespace(enabled=True, transport=SimpleNamespace(
                transports={NODE: SimpleNamespace(node=pinned)})))
        self.listing = {"nodes": [
            {"node": NODE, "execute_available": True, "execution_health": "unverified"},
            {"node": "gway-005", "execute_available": False, "execution_health": "unverified"}]}
        self.cap = {"node": NODE, "execute_available": True,
                    "execution_health": "unverified", "limits": None}

    def add(self, *, node=NODE, key=KEY, command="hostname",
            state="succeeded", at=None):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO requests VALUES (?,?,?,?,?)",
                       (node, key, command, state, (at or self.now).isoformat()))

    def test_fresh_pinned_succeeded_probe_is_verified(self):
        self.add()
        evidence = recent_probes(self.execution, now=self.now + timedelta(seconds=4))
        self.assertEqual(evidence[NODE]["execution_health"], "verified")
        self.assertEqual(evidence[NODE]["last_health_probe"]["age_seconds"], 4)
        data = project_health(self.listing, self.execution)
        self.assertEqual(data["nodes"][0]["execution_health"], "verified")
        self.assertEqual(data["nodes"][1]["execution_health"], "unverified")
        self.assertNotIn("last_health_probe", data["nodes"][1])
        self.assertEqual(project_health(self.cap, self.execution)["execution_health"], "verified")

    def test_stale_or_missing_pin_never_claims_execution_available(self):
        self.add()
        def denied(node):
            raise PermissionError("private diagnostic")
        self.execution._current_eligibility = denied
        result = project_health(self.listing, self.execution)["nodes"][0]
        self.assertFalse(result["execute_available"])
        self.assertEqual(result["execution_health"], "unverified")
        self.assertNotIn("private diagnostic", repr(result))

    def test_recent_failure_supersedes_earlier_success(self):
        self.add(at=self.now - timedelta(seconds=15))
        self.add(command="id -un", state="failed")
        evidence = recent_probes(self.execution, now=self.now + timedelta(seconds=1))
        self.assertEqual(evidence[NODE]["execution_health"], "degraded")
        self.assertEqual(evidence[NODE]["last_health_probe"]["status"], "failed")

    def test_stale_result_does_not_claim_health(self):
        self.add(at=self.now - timedelta(seconds=MAX_AGE_SECONDS + 1))
        self.assertEqual(recent_probes(self.execution, now=self.now), {})

    def test_uncertain_newer_probe_invalidates_previous_health(self):
        self.add(at=self.now - timedelta(seconds=30))
        self.add(state="uncertain")
        evidence = recent_probes(self.execution, now=self.now)
        self.assertEqual(evidence[NODE]["execution_health"], "unverified")
        self.assertNotIn("last_health_probe", evidence[NODE])

    def test_wrong_pin_node_or_unrelated_command_cannot_establish_health(self):
        self.add(command="echo hello")
        self.add(key="b" * 64)
        self.add(node="gway-005")
        self.assertEqual(recent_probes(self.execution, now=self.now), {})

    def test_future_or_corrupt_timestamp_is_not_evidence(self):
        self.add(at=self.now + timedelta(seconds=20))
        self.assertEqual(recent_probes(self.execution, now=self.now), {})
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE requests SET updated_at='invalid'")
        self.assertEqual(recent_probes(self.execution, now=self.now), {})

    def test_invalid_ledger_permissions_and_missing_db_fail_closed(self):
        self.add()
        self.path.chmod(0o644)
        self.assertEqual(recent_probes(self.execution), {})
        self.path.chmod(0o600)
        self.path.unlink()
        self.assertEqual(recent_probes(self.execution), {})

    def test_probe_read_does_not_mutate_db(self):
        self.add()
        before = self.path.read_bytes()
        self.assertEqual(recent_probes(self.execution, now=self.now)[NODE]["execution_health"],
                         "verified")
        self.assertEqual(self.path.read_bytes(), before)

    def test_disabled_relay_does_not_project_historical_success(self):
        self.add()
        self.execution.enabled = False
        self.assertEqual(recent_probes(self.execution), {})
        self.execution.enabled = True
        self.execution.relay.enabled = False
        self.assertEqual(recent_probes(self.execution), {})

    def test_gateway_list_and_capabilities_share_read_only_evidence(self):
        self.add()
        with patch("gway_remote.mcp_monitor_projection.monitor_status", return_value={"status": "failed"}), \
             patch("gway_remote.node_registry_inventory.public_nodes", return_value=self.listing), \
             patch("gway_remote.node_registry_inventory.capabilities", return_value=self.cap):
            listing = local_node_result("node_list", {}, execution=self.execution)
            capabilities = local_node_result("node_capabilities", {"node": NODE},
                                             execution=self.execution)
        self.assertEqual(listing["nodes"][0]["execution_health"], "verified")
        self.assertEqual(listing["watchtower_monitor"], {"status": "failed"})
        self.assertEqual(capabilities["execution_health"], "verified")
        self.assertIsNone(capabilities["limits"])
        self.assertNotIn("principal", json.dumps(listing))
        self.assertNotIn("command", json.dumps(capabilities))

    def test_bridge_inventory_and_capabilities_project_same_evidence(self):
        self.add()
        class Verifier:
            def verify(self, token, *, required_scope):
                return token == "trusted" and required_scope == "gway:read"
        inventory = SimpleNamespace(
            public_nodes=lambda *, execution_enabled: self.listing,
            capabilities=lambda node, *, execution_enabled: self.cap)
        dispatcher = SessionBridgeDispatch(
            verifier=Verifier(), session_token="trusted",
            allowed_node=lambda token, node: True,
            read_principal=lambda token: "reader",
            execution=self.execution, inventory=inventory)
        base = {"principal": "reader", "scope": "gway:read",
                "audience": "gway-000"}
        with patch("gway_remote.mcp_monitor_projection.monitor_status", return_value={"status": "failed"}):
            listed = dispatcher({**base, "operation": "inventory.list", "arguments": {}})
        detail = dispatcher({**base, "operation": "inventory.capabilities",
                             "arguments": {"node": NODE}})
        self.assertEqual(listed["nodes"][0]["execution_health"], "verified")
        self.assertEqual(listed["watchtower_monitor"], {"status": "failed"})
        self.assertEqual(detail["execution_health"], "verified")


if __name__ == "__main__":
    unittest.main()
