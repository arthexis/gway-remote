import unittest
from pathlib import Path


class ProvisioningTests(unittest.TestCase):
    def test_role_only_installs_cli_and_checks_status(self):
        tasks = Path("ansible/roles/gway_remote/tasks/main.yml").read_text()
        self.assertIn("install-cli.sh", tasks)
        self.assertIn("gway-remote status --json", tasks)
        self.assertIn("/etc/gway-remote/deployment.yml", tasks)
        self.assertIn("gway-004", tasks)
        self.assertIn("remote_inspection_allowed", tasks)
        self.assertIn("changed_when: false", tasks)
        self.assertNotIn("deploy-batch", tasks)
        self.assertNotIn("systemctl", tasks)

    def test_runtime_policy_is_not_bundled_below_zipapp_path(self):
        policy = Path("gway_remote/deployment_policy.py").read_text()
        self.assertIn('Path("/etc/gway-remote/deployment.yml")', policy)
        self.assertNotIn('parents[1] / "ansible"', policy)

    def test_seed_installer_is_shipped_but_not_executed(self):
        """Deployment must deliver the reviewed script without applying it."""
        source = Path("ansible/roles/gway_remote/tasks/main.yml").read_text()
        heading = "- name: Install opt-in Agent Ops seed workspace configurator"
        self.assertEqual(source.count(heading), 1)
        section = source.split(heading, 1)[1].split("\n- name:", 1)[0]
        self.assertIn("ansible.builtin.copy:", section)
        self.assertIn("scripts/configure-agent-seed-workspace.sh", section)
        self.assertIn('mode: "0755"', section)
        self.assertIn("owner: root", section)
        self.assertIn("group: root", section)
        self.assertTrue(Path("scripts/configure-agent-seed-workspace.sh").is_file())
        self.assertNotIn("cmd: sh {{ gway_remote_install_root }}/scripts/configure-agent-seed-workspace.sh", source)

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
