"""Static contract for removing only the obsolete dedicated deployment privilege path."""
from pathlib import Path
import unittest

ROLE = Path("ansible/roles/gway_remote/tasks/node-mcp-deploy.yml")
MAIN = Path("ansible/roles/gway_remote/tasks/main.yml")


class LegacyDeployRetirementTests(unittest.TestCase):
    def test_retirement_is_idempotent_and_does_not_grant_privilege(self):
        text = ROLE.read_text()
        self.assertIn("ansible.builtin.service_facts:", text)
        self.assertIn("ansible.builtin.file:", text)
        self.assertIn("state: absent", text)
        self.assertIn("gway-remote-deploy.service", text)
        self.assertIn("/etc/sudoers.d/gway-remote-mcp-deploy", text)
        self.assertIn("daemon_reload: true", text)
        self.assertNotIn("NOPASSWD:", text)
        self.assertNotIn("state: started", text)
        self.assertNotIn("state: present", text)
        self.assertIn('mode: "0700"', text)

    def test_executor_selected_before_private_receipts(self):
        text = MAIN.read_text()
        self.assertLess(text.index("node-exec-select.yml"), text.index("node-mcp-deploy.yml"))


if __name__ == "__main__":
    unittest.main()
