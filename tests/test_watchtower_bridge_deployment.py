"""Regression contracts for the Watchtower MCP bridge deployment.

These tests are static safeguards; an isolated Ansible convergence and authenticated
bridge acceptance test are still required before production activation.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible/playbooks/watchtower-mcp.yml"
BRIDGE_TASKS = ROOT / "ansible/roles/gway_remote/tasks/watchtower-mcp-bridge.yml"


class WatchtowerBridgeDeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playbook = PLAYBOOK.read_text(encoding="utf-8")
        cls.tasks = BRIDGE_TASKS.read_text(encoding="utf-8")

    def test_opt_in_is_explicitly_scoped_to_watchtower_playbook(self):
        self.assertRegex(self.playbook, r"(?m)^    gway_mcp_bridge_enable: true$")
        self.assertIn("gway_mcp_bridge_enable | default(false)", self.tasks)
        self.assertNotIn("inventory_hostname == 'watchtower'", self.playbook)

    def test_environment_change_triggers_restart(self):
        self.assertIn("register: bridge_gateway_env", self.tasks)
        restart = self.playbook.split(
            "- name: Restart the dedicated MCP gateway for new protocol code or bridge configuration", 1
        )[1].split("- name:", 1)[0]
        self.assertIn("bridge_gateway_env.changed", restart)
        self.assertIn("bridge_gateway_dropin.changed", restart)

    def test_socket_validation_is_conditional_and_strict(self):
        self.assertIn("mcp_bridge_socket.stat.issock | default(false)", self.playbook)
        self.assertIn("mcp_bridge_socket.stat.pw_name == 'gway-mcp-gateway'", self.playbook)
        self.assertIn("mcp_bridge_socket.stat.mode == '0600'", self.playbook)
        self.assertGreaterEqual(self.playbook.count("when: gway_mcp_bridge_enable | bool"), 2)

    def test_recovery_restores_previous_bridge_configuration(self):
        rescue = self.playbook.split("      rescue:", 1)[1]
        self.assertIn("mcp_bridge_original_contents.results", rescue)
        self.assertIn("mcp_bridge_original_stats.results", rescue)
        self.assertIn("mcp_original_target.stdout", rescue)
        self.assertIn("bridge_gateway_env.changed", rescue)
        self.assertIn("Verify recovered gateway route responds", rescue)

    def test_recovery_snapshots_precede_activation(self):
        self.assertLess(
            self.playbook.index("Capture original bridge configuration for recovery"),
            self.playbook.index("Provision private bridge for this Watchtower playbook target"),
        )

    def test_bridge_secrets_are_not_logged(self):
        self.assertIn("no_log: true", self.tasks)
        self.assertIn("no_log: true", self.playbook)
        self.assertIn("GWAY_MCP_BRIDGE_ENABLED={{ '1' if", self.tasks)


if __name__ == "__main__":
    unittest.main()
