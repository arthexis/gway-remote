"""Focused safety tests for passive Watchtower execution diagnostics."""
import unittest
from unittest.mock import patch

from gway_remote.watchtower_exec_diagnostic import diagnose, STAGES


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.inventory = {"nodes": [{"node": "gway-002", "registered": True,
            "identity_verified": True, "execute_eligible": True,
            "reachable": "reachable", "address": "192.0.2.1"}]}

    def test_eligible_is_not_execution_health(self):
        result = diagnose("gway-002", inventory=self.inventory,
                          config={"enabled": True, "nodes": [{"node": "gway-002",
                          "identity_file": "DO_NOT_DISCLOSE"}]})
        self.assertEqual(set(result["stages"]), set(STAGES))
        self.assertEqual(result["stages"]["current_eligibility"], "pass")
        self.assertEqual(result["stages"]["pinned_transport"], "configured")
        self.assertEqual(result["stages"]["ssh_transport"], "unknown")
        self.assertEqual(result["stages"]["worker_readiness"], "unknown")
        self.assertNotIn("DO_NOT_DISCLOSE", str(result))
        self.assertNotIn("192.0.2.1", str(result))

    def test_unattested_fails_closed(self):
        self.inventory["nodes"][0]["identity_verified"] = False
        result = diagnose("gway-002", inventory=self.inventory)
        self.assertEqual(result["stages"]["current_eligibility"], "failure")

    def test_unpinned_is_not_ready(self):
        result = diagnose("gway-002", inventory=self.inventory,
                          config={"enabled": True, "nodes": []})
        self.assertEqual(result["stages"]["pinned_transport"], "missing")
        self.assertEqual(result["stages"]["ssh_transport"], "blocked")

    def test_unknown_is_not_success(self):
        result = diagnose("gway-005", inventory=self.inventory)
        self.assertEqual(result["stages"]["current_eligibility"], "failure")
        self.assertEqual(result["stages"]["bridge_dispatch"], "blocked")
        self.assertEqual(result["stages"]["worker_readiness"], "blocked")

    def test_unknown_oauth_and_bridge_are_not_claimed_healthy(self):
        result = diagnose("gway-002", inventory=self.inventory,
                          config={"enabled": True, "nodes": [{"node": "gway-002"}]})
        self.assertEqual(result["stages"]["auth_scope"], "unknown")
        self.assertEqual(result["stages"]["bridge_dispatch"], "unknown")

    def test_no_transport_or_mutation(self):
        with patch("subprocess.run", side_effect=AssertionError("SSH forbidden")):
            diagnose("gway-002", inventory=self.inventory)


if __name__ == "__main__":
    unittest.main()
