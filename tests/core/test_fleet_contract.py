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

    def test_authenticated_read_only_partial_provider_collection(self):
        class Federation:
            def __init__(self):
                self.calls = []
            def discover(self):
                return [], {
                    "diagnostics__hardware": ("gway-001", "diagnostics", "hardware", "read"),
                    "diagnostics__status": ("gway-001", "diagnostics", "status", "read"),
                    "danger__exec": ("gway-001", "danger", "exec", "execute")}
            def call(self, name, arguments, *, authorized_scope):
                self.calls.append((name, arguments, authorized_scope))
                if name.endswith("status"):
                    raise OSError("offline")
                return {"schema": "gway-remote/hardware/v1", "checked_at": NOW.isoformat(),
                        "host": {"cpu_temperature_c": 51}}
        federation = Federation()
        row = collect_authenticated(INV, federation, now=NOW)["nodes"][0]
        self.assertTrue(row["hardware"]["available"])
        self.assertFalse(row["services"]["available"])
        self.assertEqual(federation.calls, [
            ("diagnostics__hardware", {}, "read"),
            ("diagnostics__status", {}, "read")])

    def test_unattested_node_never_dispatches_provider_call(self):
        class Federation:
            def discover(self):
                return [], {"diagnostics__hardware": ("gway-001", "diagnostics", "hardware", "read")}
            def call(self, *args, **kwargs):
                raise AssertionError("unauthorized dispatch")
        inventory = {**INV, "nodes": [{**INV["nodes"][0], "identity_verified": False}]}
        row = collect_authenticated(inventory, Federation(), now=NOW)["nodes"][0]
        self.assertFalse(row["hardware"]["available"])

    def test_unattested_observations_are_denied(self):
        inventory = {**INV, "nodes": [{**INV["nodes"][0], "identity_verified": False}]}
        result = project(inventory, {"gway-001": {"hardware": {"schema": "gway-remote/hardware/v1", "checked_at": NOW.isoformat(), "host": {"cpu_temperature_c": 52}}}}, now=NOW)
        self.assertFalse(result["nodes"][0]["hardware"]["available"])
