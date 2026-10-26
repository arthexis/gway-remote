"""Per-node deployment inventory must never adopt or probe remote installations."""
import json
import subprocess
import unittest
from unittest.mock import patch

from gway_remote.deployments import _node_policy, inventory


class NodeInventoryTests(unittest.TestCase):
    def test_customer_policy_is_unmanaged(self):
        output = {"_meta": {"hostvars": {"customer.gelectriic.com": {
            "remote_managed_repositories": []}}}}
        completed = subprocess.CompletedProcess([], 0, json.dumps(output), "")
        with patch("gway_remote.deployments.subprocess.run", return_value=completed):
            self.assertEqual(_node_policy("customer.gelectriic.com"), set())
            with self.assertRaises(ValueError):
                _node_policy("unlisted-host")

    def test_remote_never_uses_local_installed_evidence(self):
        with patch("gway_remote.deployments.socket.gethostname", return_value="gway-001"):
            with patch("gway_remote.deployments.main_head", return_value="a" * 40):
                def no_probe(name):
                    raise AssertionError("remote inventory must not probe local installation")
                report = inventory("ocpp-csms", node="customer.gelectriic.com",
                                   policy=set(), client=object(), installed=no_probe)
        row = report["components"][0]
        self.assertEqual(row["installed"], "unknown")
        self.assertIsNone(row["installed_sha"])
        self.assertFalse(row["managed"])
        self.assertFalse(row["deployable"])
        self.assertFalse(report["local_evidence"])

    def test_controller_management_and_unknown_revision_are_distinct(self):
        with patch("gway_remote.deployments.socket.gethostname", return_value="gway-001"):
            with patch("gway_remote.deployments.main_head", return_value="a" * 40):
                report = inventory("ocpp-csms", node="gway-001", policy={"ocpp-csms"},
                                   client=object(), attempts={}, installed=lambda name: None)
        row = report["components"][0]
        self.assertEqual(row["installed"], "unknown")
        self.assertTrue(row["managed"])
        self.assertTrue(row["deployable"])


if __name__ == "__main__":
    unittest.main()
