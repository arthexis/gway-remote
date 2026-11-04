"""Regression for unsafe Jinja expressions in Ansible relay cutover assertions."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "ansible/roles/gway_remote/tasks/node-exec-select.yml"


class CutoverAssertionTests(unittest.TestCase):
    def test_relay_policy_checked_with_executable_verifier_not_templated_condition(self):
        text = TASKS.read_text(encoding="utf-8")
        name = "    - name: Verify both live relay policies point to the selected executor"
        self.assertEqual(text.count(name), 1)
        section = text.split(name, 1)[1].split("\\n    - name:", 1)[0]
        self.assertIn("verify-exec-relay-policy.py", section)
        self.assertIn("- --user", section)
        self.assertIn("{{ gway_remote_exec_run_user }}", section)

    def test_unsafe_templated_sudo_assertion_is_removed(self):
        text = TASKS.read_text(encoding="utf-8")
        self.assertNotIn("Verify relay sudoers uses selected identity and no old protocol identity", text)
        self.assertNotIn("exec_relay_sudo_listing.stdout", text)
        self.assertIn("Verify both live relay policies point to the selected executor", text)

    def test_no_sudo_listing_used_to_authorize_cutover(self):
        text = TASKS.read_text(encoding="utf-8")
        self.assertNotIn("exec_relay_sudo_listing", text)
        self.assertIn("Recheck restored SSH/sudoers identity agreement after rollback", text)


if __name__ == "__main__":
    unittest.main()
