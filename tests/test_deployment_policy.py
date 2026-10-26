"""Deployment policy is deny-by-default and uses Ansible's native inventory."""
import json
import subprocess
import unittest
from unittest.mock import patch
from gway_remote.deployment_policy import require_local_deployment


class DeploymentPolicyTests(unittest.TestCase):
    def test_customer_denied_before_inventory_call(self):
        with patch("gway_remote.deployment_policy.subprocess.run") as run:
            with self.assertRaisesRegex(RuntimeError, "denied"):
                require_local_deployment(hostname="customer")
            run.assert_not_called()

    def test_unknown_host_denied(self):
        with self.assertRaises(RuntimeError):
            require_local_deployment(hostname="unknown-node")

    def test_approved_target(self):
        result = subprocess.CompletedProcess([], 0, json.dumps({"remote_managed_repositories": ["ocpp-csms"]}), "")
        with patch("gway_remote.deployment_policy.subprocess.run", return_value=result):
            self.assertEqual(require_local_deployment("ocpp-csms", hostname="gway-001"), ("ocpp-csms",))
            with self.assertRaisesRegex(RuntimeError, "not approved"):
                require_local_deployment("ocpp-reports", hostname="gway-001")
            with self.assertRaisesRegex(RuntimeError, "exceeds"):
                require_local_deployment(hostname="gway-001")

    def test_missing_inventory_fails_closed(self):
        with patch("gway_remote.deployment_policy.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                require_local_deployment("ocpp-csms", hostname="gway-001")


if __name__ == "__main__":
    unittest.main()
