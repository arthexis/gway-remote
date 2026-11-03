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
