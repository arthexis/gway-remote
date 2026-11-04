"""Regression for unsafe Jinja expressions in Ansible relay cutover assertions."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "ansible/roles/gway_remote/tasks/node-exec-select.yml"


class CutoverAssertionTests(unittest.TestCase):
    def test_relay_policy_checked_with_executable_verifier_not_templated_condition(self):
        tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
        block = next(item["block"] for item in tasks
                     if item.get("name") == "Activate selected execution identity and update only existing relay")
        checks = [item for item in block
                  if item.get("name") == "Verify both live relay policies point to the selected executor"]
        self.assertEqual(len(checks), 1)
        argv = checks[0]["ansible.builtin.command"]["argv"]
        self.assertTrue(any("verify-exec-relay-policy.py" in str(arg) for arg in argv))
        self.assertIn("--user", argv)
        self.assertIn("{{ gway_remote_exec_run_user }}", argv)

    def test_no_inline_template_markers_in_assert_conditions(self):
        def visit(value):
            if isinstance(value, dict):
                if "ansible.builtin.assert" in value:
                    for expression in value["ansible.builtin.assert"].get("that", []):
                        self.assertNotIn("{{", str(expression))
                        self.assertNotIn("{%", str(expression))
                for nested in value.values():
                    visit(nested)
            elif isinstance(value, list):
                for nested in value:
                    visit(nested)
        visit(yaml.safe_load(TASKS.read_text(encoding="utf-8")))

    def test_no_sudo_listing_used_to_authorize_cutover(self):
        text = TASKS.read_text(encoding="utf-8")
        self.assertNotIn("exec_relay_sudo_listing", text)
        self.assertIn("Recheck restored SSH/sudoers identity agreement after rollback", text)


if __name__ == "__main__":
    unittest.main()
