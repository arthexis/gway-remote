"""Regression checks for runner-user Ansible tasks on Linux hosts without ACL support."""

from pathlib import Path
import unittest

ROLE_TASKS = Path(__file__).resolve().parents[1] / "ansible/roles/gway_remote/tasks/main.yml"


class RunnerVerificationTests(unittest.TestCase):
    def test_checks_use_sudo_without_ansible_unprivileged_become(self):
        text = ROLE_TASKS.read_text()
        for task_name in (
            "Verify read-only status JSON as runner user",
            "Verify API snapshot path is readable by appliance runner",
        ):
            section = text.split("- name: " + task_name + "\n", 1)[1].split("\n- name: ", 1)[0]
            self.assertNotIn("become_user:", section)
            self.assertIn("- /usr/bin/sudo", section)
            self.assertIn("- -n", section)
            self.assertIn("- -H", section)
            self.assertIn("- -u", section)
            self.assertIn('- "{{ gway_remote_runner_user }}"', section)
            self.assertIn("changed_when: false", section)

    def test_status_contract_and_snapshot_protection_remain(self):
        text = ROLE_TASKS.read_text()
        self.assertIn("gway-remote/status/v1", text)
        self.assertIn("- --json", text)
        self.assertIn('os.access(path, os.R_OK | os.X_OK)', text)
        self.assertIn('os.access(snapshot, os.R_OK)', text)


if __name__ == "__main__":
    unittest.main()
