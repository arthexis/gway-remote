import unittest
from pathlib import Path


class ProvisioningTests(unittest.TestCase):
    def test_role_only_installs_cli_and_checks_status(self):
        tasks = Path("ansible/roles/gway_remote/tasks/main.yml").read_text()
        self.assertIn("install-cli.sh", tasks)
        self.assertIn("gway-remote status --json", tasks)
        self.assertIn("changed_when: false", tasks)
        self.assertNotIn("deploy-batch", tasks)
        self.assertNotIn("systemctl", tasks)

    def test_playbook_requires_explicit_inventory(self):
        playbook = Path("ansible/playbook.yml").read_text()
        self.assertIn("hosts: gway_remote", playbook)
        self.assertIn("gway_remote", playbook)


if __name__ == "__main__":
    unittest.main()
