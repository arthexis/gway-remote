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
            "Validate each pinned MCP provider",
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
        self.assertNotIn("item.permission", source)
        self.assertIn("follow: false", source)
        self.assertIn("checksum_algorithm: sha256", source)

    def test_opt_in_legacy_policy_never_writes_node_owned_manifests(self):
        source = TASKS.read_text(encoding="utf-8")
        self.assertIn("Install registration-only MCP policy", source)
        self.assertIn("Validate installed provider discovery", source)
        self.assertIn("discover_installed_providers", source)
        self.assertIn("changed_when: false", source)
        # The previous optional role used ansible.builtin.copy to overwrite
        # /etc/gway-mcp-providers/<source_id>.json whenever gway_mcp_sources
        # was provided. Even explicit policy staging must not own Odoo/AgentOps.
        self.assertNotIn("Publish installed MCP provider manifests", source)
        self.assertNotIn("Create administrative provider manifest directory", source)
        self.assertNotIn("/etc/gway-mcp-providers/", source)
        self.assertNotIn("item.source_id }}.json", source)
        self.assertNotIn("converge-mcp-manifests.py", source)

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
