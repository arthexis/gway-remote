"""Watchtower MCP lifecycle must use the normal Ansible deploy entrypoint.

No automatic first-time enrollment, credential creation, Nginx public
exposure, or restarting other services.
"""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "deploy.sh"
PLAYBOOK = ROOT / "ansible/playbooks/watchtower-mcp.yml"


class WatchtowerMCPDeployContract(unittest.TestCase):
    def test_standard_deploy_calls_separate_mcp_ansible_when_enabled(self):
        text = WRAPPER.read_text()
        self.assertIn("ansible/playbooks/watchtower-mcp.yml", text)
        self.assertIn("ansible/playbook.yml", text)
        self.assertIn("/etc/gway-mcp-gateway/link.env", text)
        self.assertIn("systemctl is-enabled --quiet gway-mcp-link.service", text)
        self.assertIn("GWAY_REMOTE_SKIP_MCP", text)
        self.assertIn("flock -n 9", text)
        self.assertLess(text.index("watchtower-mcp.yml"), text.index("# This marker is only a hint"))
        outcome = subprocess.run(["sh", "-n", str(WRAPPER)], text=True, capture_output=True)
        self.assertEqual(outcome.returncode, 0, outcome.stderr)

    def test_mcp_ansible_scoped_to_isolated_runtime_and_oauth_service(self):
        text = PLAYBOOK.read_text()
        for required in (
            "stage-mcp-runtime.py", "/opt/gway-mcp/current/run.py",
            "gway-mcp-link.service", "mcp_sha.stdout",
            "authorization_response_iss_parameter_supported",
            "mcp_original_target", "mcp_original_unit",
            "ansible.builtin.uri", "rescue:", "mv -Tf",
            "gway-mcp-gateway.service",
        ):
            self.assertIn(required, text)
        for forbidden in (
            "nginx", "gway-remote-mobile-api.service", "ocpp-csms",
            "ocpp-reports", "ssh-config", "authorized_keys",
            "gway-mcp-private-bridge.service",
            "link.env\n            content:", "state: enabled",
            "apt:", "pip:",
        ):
            self.assertNotIn(forbidden, text)

    def test_workspace_bridge_uses_preexisting_key_and_is_enabled_on_reviewed_rollout(self):
        play = PLAYBOOK.read_text()
        bridge = (ROOT / "ansible/roles/gway_remote/tasks/watchtower-mcp-bridge.yml").read_text()
        dropin = (ROOT / "ansible/roles/gway_remote/tasks/watchtower-mcp-bridge-systemd.yml").read_text()
        self.assertIn("gway_mcp_bridge_enable: true", play)
        self.assertIn("Require pre-existing bridge key for gateway activation", bridge)
        self.assertLess(bridge.index("Require pre-existing bridge key for gateway activation"),
                        bridge.index("Generate private bridge key once"))
        self.assertIn("bridge_key.stat.exists", bridge)
        self.assertIn("when: gway_mcp_bridge_enable | default(false) | bool", bridge)
        self.assertIn("GWAY_MCP_BRIDGE_ENABLED={{ '1' if", bridge)
        self.assertIn("register: bridge_gateway_env", bridge)
        self.assertIn("EnvironmentFile=/etc/gway-mcp/bridge/gateway.env", dropin)
        self.assertIn("bridge_gateway_env.changed | default(false)", play)
        self.assertIn("bridge_gateway_dropin.changed | default(false)", play)
        # No new SSH identity or separate approval is introduced.
        self.assertNotIn("ssh-keygen", play)
        self.assertNotIn("operator_approved", bridge)

    def test_failed_gateway_rollout_restores_prior_bridge_settings(self):
        play = PLAYBOOK.read_text()
        self.assertIn("Inspect existing private bridge settings for rollback", play)
        self.assertIn("Read existing bridge settings byte-for-byte before update", play)
        self.assertIn("Restore prior private bridge settings on failure", play)
        self.assertIn("Remove bridge settings created by failed activation", play)
        self.assertIn("bridge_previous_contents.results", play)
        self.assertIn("no_log: true", play)
        self.assertLess(play.index("Read existing bridge settings byte-for-byte before update"),
                        play.index("Stage and activate only the dedicated MCP runtime"))
        self.assertGreater(play.index("Restore prior private bridge settings on failure"),
                           play.index("rescue:"))

    def test_protected_inventory_verification_uses_task_local_become(self):
        # Do not chmod the auth directory or add the operator to a group
        # that also exposes the Watchtower bearer credential registry.
        text = PLAYBOOK.read_text()
        verification = text.split(
            "- name: Verify dynamic inventory can read registered hosts", 1
        )[1].split("- name: Validate Ansible export", 1)[0]
        self.assertIn("become: true", verification)
        self.assertIn("/usr/local/sbin/gway-enrolled-inventory", verification)
        self.assertNotIn("mode:", verification)
        self.assertNotIn("group:", verification)
        self.assertNotIn("user:", verification)

    def test_never_starts_new_watchtower_on_bootstrap(self):
        text = WRAPPER.read_text()
        self.assertIn("[ -f /etc/gway-mcp-gateway/link.env ]", text)
        self.assertNotIn("stage.sh", text)
        # Existing caller-specific Watchtower deployment is opt-in by state;
        # no first-time token issuance or Nginx route activation.
        yml = PLAYBOOK.read_text()
        self.assertIn("Refuse first-time deployment", yml)
        self.assertIn("mcp_prerequisites.results[0].stat.isreg", yml)
        self.assertIn("mcp_prerequisites.results[2].stat.islnk", yml)


if __name__ == "__main__":
    unittest.main()
