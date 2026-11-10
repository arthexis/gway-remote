"""Guard the installer-only dormant SSH opt-in against legacy account regressions."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class InstallerOnlyOptInTests(unittest.TestCase):
    def test_opt_in_is_not_included_by_default(self):
        main = (ROOT / "ansible/roles/gway_remote/tasks/main.yml").read_text()
        self.assertNotIn("include_tasks: node-exec-opt-in.yml", main)

    def test_opt_in_is_key_scoped_and_nonexclusive(self):
        recipe = (ROOT / "ansible/roles/gway_remote/tasks/node-exec-opt-in.yml").read_text()
        self.assertIn("gway_remote_runner_user", recipe)
        self.assertIn("gway_remote_executor_opt_in", recipe)
        self.assertIn("restrict,command=", recipe)
        self.assertIn("exclusive: false", recipe)
        self.assertIn("manage_dir: false", recipe)
        for forbidden in ("sudo -u", "gway-exec", "gway-relay",
                          "Match User", "sshd_config", "pty: true"):
            self.assertNotIn(forbidden, recipe)

    def test_inventory_does_not_resolve_installer_from_ledger(self):
        inventory = (ROOT / "gway_remote/node_registry_inventory.py").read_text()
        self.assertNotIn("installer_identity_bindings", inventory)
        self.assertNotIn("installer_binding", inventory)


if __name__ == "__main__":
    unittest.main()
