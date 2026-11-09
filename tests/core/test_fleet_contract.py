import unittest
from datetime import datetime, timezone, timedelta
from gway_remote.fleet_contract import project

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

    def test_unattested_observations_are_denied(self):
        inventory = {**INV, "nodes": [{**INV["nodes"][0], "identity_verified": False}]}
        result = project(inventory, {"gway-001": {"hardware": {"schema": "gway-remote/hardware/v1", "checked_at": NOW.isoformat(), "host": {"cpu_temperature_c": 52}}}}, now=NOW)
        self.assertFalse(result["nodes"][0]["hardware"]["available"])
