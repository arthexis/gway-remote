"""Regression: normal GWay deployment must not inspect Odoo source."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OdooDeploymentIsolationTests(unittest.TestCase):
    def test_normal_role_does_not_include_odoo_tasks(self):
        role = (ROOT / "ansible/roles/gway_remote/tasks/main.yml").read_text()
        self.assertNotIn("odoo-gelectriic.yml", role)
        self.assertNotIn("Install Odoo Gelectriic command suite", role)

    def test_independent_odoo_task_file_retained_for_migration(self):
        self.assertTrue((ROOT / "ansible/roles/gway_remote/tasks/odoo-gelectriic.yml").is_file())


if __name__ == "__main__":
    unittest.main()
