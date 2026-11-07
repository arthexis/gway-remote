"""Structural contracts for Ansible MCP policy staging."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "ansible/roles/gway_remote/tasks/mcp-source-provision.yml"
ENTRY = ROOT / "ansible/playbooks/validate-mcp-source-provision.yml"
CI = ROOT / ".github/workflows/ci.yml"


class TestAnsibleMcpPolicyContract(unittest.TestCase):
    def test_policy_tasks_have_single_lifecycle(self):
        source = TASKS.read_text(encoding="utf-8")
        for name in (
            "Validate MCP source registrations",
            "Validate each pinned read-only MCP provider",
            "Inspect existing policy without following symlinks",
            "Install registration-only MCP policy",
            "Validate staged policy with installed package parser",
            "Compute staged policy checksum",
            "Assert verified digest",
        ):
            with self.subTest(task=name):
                self.assertEqual(source.count("- name: " + name), 1)

    def test_no_secondary_approval_or_automatic_activation(self):
        source = TASKS.read_text(encoding="utf-8")
        self.assertNotIn("gway_mcp_policy_replace_approved", source)
        self.assertNotIn("ansible.builtin.systemd:", source)
        self.assertNotIn("ansible.builtin.service:", source)
        self.assertIn("item.permission == 'read'", source)
        self.assertIn("follow: false", source)
        self.assertIn("checksum_algorithm: sha256", source)

    def test_static_import_is_checked_in_both_ansible_jobs(self):
        entry = ENTRY.read_text(encoding="utf-8")
        ci = CI.read_text(encoding="utf-8")
        self.assertIn(
            "ansible.builtin.import_tasks: ../roles/gway_remote/tasks/mcp-source-provision.yml",
            entry,
        )
        self.assertEqual(ci.count("ansible/playbooks/validate-mcp-source-provision.yml"), 2)


if __name__ == "__main__":
    unittest.main()
