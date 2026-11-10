"""Static contract for removing only the obsolete dedicated deployment privilege path."""
from pathlib import Path
import unittest

ROLE = Path("ansible/roles/gway_remote/tasks/node-mcp-deploy.yml")
MAIN = Path("ansible/roles/gway_remote/tasks/main.yml")
DEFAULTS = Path("ansible/roles/gway_remote/defaults/main.yml")
SELECT = Path("ansible/roles/gway_remote/tasks/node-exec-select.yml")


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

    def test_single_effective_identity_for_pilot_and_other_nodes(self):
        defaults = DEFAULTS.read_text()
        self.assertIn("gway_remote_exec_run_user:", defaults)
        self.assertIn("'arthe' if (ansible_hostname", defaults)
        self.assertIn("else 'gway-exec'", defaults)
        self.assertNotIn("gway_remote_exec_user:", defaults)
        select = SELECT.read_text()
        self.assertIn("gway_remote_exec_run_user in ['gway-exec', 'arthe']", select)
        self.assertIn("gway_remote_exec_run_user != 'arthe' or (ansible_hostname", select)
        self.assertIn('{"user": {{ gway_remote_exec_run_user | to_json }}}', select)
        self.assertIn("gway-relay ALL=({{ gway_remote_exec_run_user }})", select)

    def test_private_receipts_and_worker_share_selected_identity(self):
        role = ROLE.read_text()
        main = MAIN.read_text()
        self.assertIn('key: "{{ gway_remote_exec_run_user }}"', role)
        self.assertIn('owner: "{{ gway_remote_exec_run_user }}"', role)
        self.assertIn('group: "{{ gway_remote_exec_run_user }}"', role)
        self.assertIn('mode: "0700"', role)
        self.assertNotIn("gway_remote_exec_user", role)
        self.assertIn('      - "{{ gway_remote_exec_run_user }}"', main)
        self.assertNotIn("gway_remote_exec_user", main)
        self.assertNotIn("NOPASSWD:", role)
        self.assertNotIn("state: started", role)

    def test_executor_selected_before_private_receipts(self):
        text = MAIN.read_text()
        self.assertLess(text.index("node-exec-select.yml"), text.index("node-mcp-deploy.yml"))


if __name__ == "__main__":
    unittest.main()
