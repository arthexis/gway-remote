"""Regression coverage for the actual hosted admission workflow script.

The checked-out inventory is for hosted admission only; appliance execution
continues to use the protected installed inventory by default.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import unittest
from unittest.mock import patch

from gway_remote.deployment_policy import INVENTORY, require_local_deployment


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/appliance-deploy.yml"
ADMISSION_INVENTORY = "ansible/inventory/deployment.yml"


def admission_script():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(
        r"      - name: Reject unapproved target before deployment jobs\n"
        r".*?          python3 - <<'PY'\n(.*?)\n          PY\n",
        workflow,
        re.DOTALL,
    )
    if not match:
        raise AssertionError("Hosted admission script was not found")
    return "\n".join(line.removeprefix("          ") for line in match.group(1).splitlines())


class HostedAdmissionTests(unittest.TestCase):
    def execute(self, *, actor="arthexis", node="gway-001", repository="ocpp-csms"):
        environment = {
            "REQUEST_ACTOR": actor,
            "REQUESTED_NODE": node,
            "REQUESTED_REPOSITORY": repository,
        }
        with patch.dict(os.environ, environment):
            exec(compile(admission_script(), str(WORKFLOW), "exec"), {"__name__": "__main__"})

    def test_single_target_uses_checked_out_inventory(self):
        with patch("gway_remote.deployment_policy.require_local_deployment") as admit:
            self.execute()
        admit.assert_called_once_with(
            "ocpp-csms", hostname="gway-001", inventory=ADMISSION_INVENTORY
        )

    def test_full_batch_uses_checked_out_inventory(self):
        with patch("gway_remote.deployment_policy.require_local_deployment") as admit:
            self.execute(repository="all")
        admit.assert_called_once_with(
            None, hostname="gway-001", inventory=ADMISSION_INVENTORY
        )

    def test_unapproved_actor_and_node_denied_before_policy(self):
        for arguments in ({"actor": "unauthorized"}, {"node": "gway-004"}):
            with self.subTest(arguments=arguments):
                with patch("gway_remote.deployment_policy.require_local_deployment") as admit:
                    with self.assertRaises(SystemExit):
                        self.execute(**arguments)
                    admit.assert_not_called()

    def test_missing_or_invalid_inventory_denied(self):
        for error in (
            FileNotFoundError("inventory missing"),
            subprocess.CalledProcessError(1, ["ansible-inventory"]),
        ):
            with self.subTest(error=type(error).__name__):
                with patch("gway_remote.deployment_policy.subprocess.run", side_effect=error):
                    with self.assertRaisesRegex(RuntimeError, "unavailable"):
                        self.execute()

    def test_empty_and_insufficient_inventory_denied(self):
        for repositories, requested, expected in (
            ([], "ocpp-csms", "No approved"),
            (["ocpp-csms"], "ocpp-reports", "not approved"),
            (["ocpp-csms"], "all", "exceeds"),
        ):
            with self.subTest(repositories=repositories, requested=requested):
                result = subprocess.CompletedProcess(
                    [], 0,
                    json.dumps({"remote_managed_repositories": repositories}), "",
                )
                with patch("gway_remote.deployment_policy.subprocess.run", return_value=result):
                    with self.assertRaisesRegex(RuntimeError, expected):
                        self.execute(repository=requested)

    def test_appliance_default_remains_protected(self):
        self.assertEqual(str(INVENTORY), "/etc/gway-remote/deployment.yml")
        self.assertEqual(
            require_local_deployment.__kwdefaults__["inventory"], INVENTORY
        )


if __name__ == "__main__":
    unittest.main()
