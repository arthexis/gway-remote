import unittest
from datetime import datetime, timezone, timedelta
from gway_remote.fleet_contract import project, collect_authenticated

NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)
INV = {"source": "watchtower-enrollment-ledger", "generated_at": NOW.isoformat(), "nodes": [{"node": "gway-001", "identity_verified": True, "reachable": "unknown"}]}


class TestFleetContract(unittest.TestCase):
    def test_missing_observations_are_unknown(self):
        row = project(INV, now=NOW)["nodes"][0]
        self.assertFalse(row["hardware"]["available"])
        self.assertFalse(row["services"]["available"])
        self.assertEqual(row["deployments"]["components"], [])

    def test_rejects_untrusted_or_duplicate_inventory(self):
        with self.assertRaises(ValueError):
            project({"source": "other", "nodes": []}, now=NOW)
        with self.assertRaises(ValueError):
            project({**INV, "nodes": INV["nodes"] * 2}, now=NOW)

    def test_stale_observations_fail_closed(self):
        old = (NOW - timedelta(minutes=6)).isoformat()
        result = project(INV, {"gway-001": {"hardware": {"schema": "gway-remote/hardware/v1", "checked_at": old, "host": {"cpu_temperature_c": 50}}}}, now=NOW)
        self.assertFalse(result["nodes"][0]["hardware"]["available"])

    def test_fresh_observation_preserves_provenance(self):
        result = project(INV, {"gway-001": {"hardware": {"schema": "gway-remote/hardware/v1", "checked_at": NOW.isoformat(), "host": {"cpu_temperature_c": 52}}}}, now=NOW)
        self.assertEqual(result["nodes"][0]["hardware"]["data"]["cpu_temperature_c"], 52)

    def test_multinode_read_only_partial_collection(self):
        class Transport:
            def __init__(self):
                self.calls = []
            def invoke(self, node, request, *, trusted_scope):
                self.calls.append((node, request, trusted_scope))
                if request["operation"] == "provider_list":
                    return {"node": node, "providers": [{"provider": "diagnostics",
                        "node": node, "status": "available", "tools": [
                            {"name": "hardware", "annotations": {"readOnlyHint": True}},
                            {"name": "status", "annotations": {"readOnlyHint": True}},
                            {"name": "exec", "annotations": {}}]}]}
                if request["tool"] == "status":
                    raise OSError("offline")
                return {"content": [{"type": "text", "text": __import__("json").dumps({
                    "schema": "gway-remote/hardware/v1", "checked_at": NOW.isoformat(),
                    "host": {"cpu_temperature_c": 51}})}]}
        transport = Transport()
        federation = type("Federation", (), {"transport": transport})()
        inventory = {**INV, "nodes": [INV["nodes"][0], {
            "node": "gway-002", "identity_verified": True, "reachable": "unknown"}]}
        rows = collect_authenticated(inventory, federation, now=NOW)["nodes"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["hardware"]["available"] for row in rows))
        self.assertTrue(all(not row["services"]["available"] for row in rows))
        self.assertTrue(all(scope == "read" for _, _, scope in transport.calls))
        self.assertFalse(any(req.get("tool") == "exec" for _, req, _ in transport.calls))

    def test_unattested_node_never_dispatches_provider_call(self):
        class Transport:
            def invoke(self, *args, **kwargs):
                raise AssertionError("unauthorized dispatch")
        inventory = {**INV, "nodes": [{**INV["nodes"][0], "identity_verified": False}]}
        row = collect_authenticated(inventory, type("Federation", (), {"transport": Transport()})(), now=NOW)["nodes"][0]
        self.assertFalse(row["hardware"]["available"])

    def test_oversized_utf8_and_wrong_schema_are_unavailable(self):
        class Transport:
            def invoke(self, node, request, *, trusted_scope):
                if request["operation"] == "provider_list":
                    return {"node": node, "providers": [{"provider": "diagnostics",
                        "node": node, "status": "available", "tools": [
                            {"name": "hardware", "annotations": {"readOnlyHint": True}},
                            {"name": "status", "annotations": {"readOnlyHint": True}}]}]}
                if request["tool"] == "hardware":
                    return {"schema": "gway-remote/hardware/v1", "checked_at": NOW.isoformat(),
                            "host": {"model": "界" * 30000}}
                return {"schema": "untrusted/status", "checked_at": NOW.isoformat(),
                        "components": [{"name": "fake"}]}
        row = collect_authenticated(INV, type("Federation", (), {"transport": Transport()})(), now=NOW)["nodes"][0]
        self.assertFalse(row["hardware"]["available"])
        self.assertFalse(row["services"]["available"])

    def test_unattested_observations_are_denied(self):
        inventory = {**INV, "nodes": [{**INV["nodes"][0], "identity_verified": False}]}
        result = project(inventory, {"gway-001": {"hardware": {"schema": "gway-remote/hardware/v1", "checked_at": NOW.isoformat(), "host": {"cpu_temperature_c": 52}}}}, now=NOW)
        self.assertFalse(result["nodes"][0]["hardware"]["available"])
