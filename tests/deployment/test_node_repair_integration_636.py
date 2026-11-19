"""Keep issue #636 Ansible verification bounded and opt-in."""
import pathlib
import unittest
from unittest.mock import Mock, patch

from gway_remote.cli.registry import build_parser


ROOT = pathlib.Path(__file__).resolve().parents[2]


class NodeRepairIntegrationContractTests(unittest.TestCase):
    def test_existing_cli_registers_node_verify_without_execute_credentials(self):
        parser = build_parser((), ())
        opts = parser.parse_args(["node", "verify", "gway-002", "--json"])
        self.assertEqual(opts.node_action, "verify")
        self.assertEqual(opts.node, "gway-002")
        self.assertTrue(opts.json)

    def test_ansible_hook_uses_existing_cli_read_only(self):
        raw = (ROOT / "ansible/playbooks/node-repair-verify.yml").read_text()
        self.assertIn("hosts: localhost", raw)
        self.assertIn("connection: local", raw)
        self.assertIn("gway_repair_node", raw)
        self.assertIn("changed_when: false", raw)
        self.assertIn("no_log: true", raw)
        self.assertIn("          - verify\n", raw)
        self.assertNotIn("ansible.builtin.shell", raw)
        self.assertNotIn("ansible.builtin.systemd", raw)
        self.assertNotIn("ansible.builtin.copy", raw)
        self.assertNotIn("ansible.builtin.user", raw)
        self.assertNotIn("curl ", raw)

    def test_node_inventory_remains_production_and_non_deployable(self):
        inventory = (ROOT / "ansible/inventory/deployment.yml").read_text()
        production = inventory.split("    production:\n", 1)[1]
        node = production.split("        gway-002:\n", 1)[1].split("        gway-005:\n", 1)[0]
        self.assertIn("remote_managed_repositories: []", node)


if __name__ == "__main__":
    unittest.main()
