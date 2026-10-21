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

    def test_agent_workspace_installer_is_shipped_but_not_executed(self):
        tasks = Path("ansible/roles/gway_remote/tasks/main.yml").read_text()
        script = "configure-agent-seed-workspace.sh"
        self.assertTrue((Path("scripts") / script).is_file())
        self.assertIn('src: "{{ playbook_dir }}/../scripts/' + script + '"', tasks)
        self.assertIn('dest: "{{ gway_remote_install_root }}/scripts/' + script + '"', tasks)
        self.assertIn('mode: "0755"', tasks)
        self.assertNotIn("sh {{ gway_remote_install_root }}/scripts/" + script, tasks)

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
