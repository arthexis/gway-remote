"""Verify Odoo CLIs are managed on gway-001 by the existing Ansible role."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class OdooCliDeployTests(unittest.TestCase):
    def test_controller_inventory_only(self):
        inventory = (ROOT / "ansible/inventory/deployment.yml").read_text()
        controller = inventory.split("gway-001:", 1)[1].split("quality:", 1)[0]
        self.assertIn("- odoo-gelectriic", controller)
        for section in ("gway-004:", "gway-002:", "gway-005:"):
            self.assertIn(section, inventory)
        self.assertEqual(inventory.count("- odoo-gelectriic"), 1)

    def test_role_is_controller_only_and_uses_system_owned_binaries(self):
        role = (ROOT / "ansible/roles/gway_remote/tasks/main.yml").read_text()
        self.assertIn("include_tasks: odoo-gelectriic.yml", role)
        self.assertIn("(ansible_hostname | default('')) == 'gway-001'", role)
        play = (ROOT / "ansible/roles/gway_remote/tasks/odoo-gelectriic.yml").read_text()
        self.assertIn("pull, --ff-only, origin, main", play)
        self.assertIn("status, --porcelain", play)
        self.assertIn("become_user: \"{{ gway_remote_runner_user }}\"", play)
        self.assertIn("gway_odoo_bin_root: /opt/odoo-gelectriic/bin", play)
        self.assertIn("dest: \"/usr/local/bin/{{ item }}\"", play)
        self.assertIn("owner: root", play)
        self.assertIn("mode: '0755'", play)
        self.assertIn("Refusing to replace unrelated", play)
        for name in ("odoo-gelectriic", "odoo-domain", "odoo-query", "odoo-bom",
                     "odoo-credentials", "odoo-quotation", "odoo-quotation-write",
                     "odoo-quotation-pdf", "odoo-catalog"):
            self.assertIn("- " + name, play)
        self.assertIn("- catalog", play)
        self.assertIn("- inspect", play)
        self.assertNotIn("gway_odoo_data_root", play)
        self.assertNotIn("data/", play)
        self.assertNotIn("active.quotation.toml.enc", play)
        self.assertNotIn("passphrase", play)

    def test_mobile_backend_uses_system_install(self):
        bridge = (ROOT / "gway_remote/mobile_odoo_quotations.py").read_text()
        self.assertIn('ROOT = Path("/opt/odoo-gelectriic/bin")', bridge)
        self.assertNotIn('ROOT = Path.home() / "Repos"', bridge)
