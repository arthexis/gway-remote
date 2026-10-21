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

    def test_seed_installer_is_shipped_but_not_executed(self):
        """Deployment must deliver the reviewed script without applying it."""
        import yaml
        tasks = yaml.safe_load(Path("ansible/roles/gway_remote/tasks/main.yml").read_text())
        matches = [task for task in tasks if task.get("name") ==
                   "Install opt-in Agent Ops seed workspace configurator"]
        self.assertEqual(len(matches), 1)
        copy = matches[0]["ansible.builtin.copy"]
        self.assertTrue(copy["src"].endswith("/scripts/configure-agent-seed-workspace.sh"))
        self.assertEqual(copy["dest"], "{{ gway_remote_install_root }}/scripts/configure-agent-seed-workspace.sh")
        self.assertEqual(copy["mode"], "0755")
        self.assertEqual(copy["owner"], "root")
        self.assertEqual(copy["group"], "root")
        self.assertTrue(Path("scripts/configure-agent-seed-workspace.sh").is_file())
        for task in tasks:
            if task is matches[0]:
                continue
            self.assertNotIn("configure-agent-seed-workspace.sh",
                             str(task.get("ansible.builtin.command", "")))

    def test_local_deploy_wrapper(self):
        script = Path('deploy.sh').read_text()
        self.assertIn('ansible-playbook', script)
        self.assertIn("-i 'gway_remote,' -c local", script)

    def test_playbook_requires_explicit_inventory(self):
        playbook = Path("ansible/playbook.yml").read_text()
        self.assertIn("hosts: gway_remote", playbook)
        self.assertIn("gway_remote", playbook)

    def test_sound_helper_is_provisioned_root_owned(self):
        tasks = Path("ansible/roles/gway_remote/tasks/main.yml").read_text()
        self.assertIn("scripts/gway-promote-sound", tasks)
        self.assertIn("dest: /usr/local/sbin/gway-promote-sound", tasks)
        self.assertIn("validate: \"/usr/sbin/visudo -cf %s\"", tasks)
        self.assertIn("gway_remote_runner_user", tasks)
        self.assertIn('mode: "0440"', tasks)


if __name__ == "__main__":
    unittest.main()
