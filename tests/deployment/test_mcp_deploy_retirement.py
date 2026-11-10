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

    def test_new_remote_execution_is_not_implicitly_activated(self):
        main = MAIN.read_text()
        defaults = DEFAULTS.read_text()
        for name in ("node-exec-prepare.yml", "node-exec-select.yml",
                     "node-exec-relay.yml", "node-mcp-deploy.yml"):
            self.assertNotIn("include_tasks: " + name, main)
        self.assertNotIn("gway_remote_exec_user", defaults)
        self.assertNotIn("gway_remote_exec_run_user", defaults)

    def test_general_release_rollback_is_not_yet_implemented(self):
        # Document the acceptance gap, not a fictitious rollback guarantee.
        deploy = Path("deploy.sh").read_text()
        self.assertIn('ansible-playbook "$ROOT/ansible/playbook.yml"', deploy)
        self.assertIn('mv -f "$tmp" "$marker"', deploy)
        self.assertNotIn("rollback-release.yml", deploy)

    def test_legacy_receipts_are_not_part_of_normal_install(self):
        main = MAIN.read_text()
        self.assertNotIn("include_tasks: node-mcp-deploy.yml", main)
        self.assertNotIn("include_tasks: node-exec-select.yml", main)
        self.assertNotIn("gway_remote_exec_run_user", main)

    def test_runner_paths_use_passwd_home_not_name_concatenation(self):
        main = MAIN.read_text()
        self.assertIn("register: gway_remote_runner_passwd", main)
        self.assertIn("gway_remote_runner_passwd.ansible_facts.getent_passwd[gway_remote_runner_user][4]", main)
        self.assertNotIn("/home/{{ gway_remote_runner_user }}", main)

    def test_no_legacy_cutover_in_normal_role(self):
        text = MAIN.read_text()
        self.assertNotIn("node-exec-select.yml", text)
        self.assertNotIn("node-mcp-deploy.yml", text)

