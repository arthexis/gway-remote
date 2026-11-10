"""Offline opt-in boundary tests. Never invoke Ansible or modify authorized_keys."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
RECIPE = ROOT / "ansible/roles/gway_remote/tasks/node-exec-opt-in.yml"
DEPLOY = ROOT / "deploy.sh"


class ExecutorOptInBoundaryTests(unittest.TestCase):
    def test_install_identity_is_captured_by_deploy_without_switching_users(self):
        script = DEPLOY.read_text()
        self.assertIn('$(id -u)', script)
        self.assertIn('$(id -un)', script)
        self.assertIn('gway_remote_runner_user=', script)
        self.assertIn('gway_remote_runner_uid=', script)
        self.assertNotIn("sudo -u", script)

    def test_opt_in_is_explicit_and_never_in_default_role(self):
        recipe = RECIPE.read_text()
        main = (RECIPE.parent / "main.yml").read_text()
        self.assertIn("gway_remote_executor_opt_in | default(false) | bool", recipe)
        self.assertNotIn("node-exec-opt-in.yml", main)
        self.assertIn("gway_remote_runner_user == lookup('pipe', 'id -un')", recipe)
        self.assertIn("(gway_remote_runner_uid | int) == (lookup('pipe', 'id -u') | int)", recipe)
        self.assertIn("gway_remote_runner_user != 'root'", recipe)

    def test_authorized_key_is_dedicated_restricted_and_nonexclusive(self):
        recipe = RECIPE.read_text()
        self.assertIn('restrict,command="/usr/local/libexec/gway-remote-exec-protocol-v1"', recipe)
        self.assertIn("exclusive: false", recipe)
        self.assertIn("manage_dir: false", recipe)
        self.assertIn("state: present", recipe)
        self.assertLess(recipe.index("Install reviewed fixed-command entrypoint"),
                        recipe.index("Install dedicated restricted executor key"))
        self.assertIn("follow: false", recipe)
        self.assertNotIn("sshd_config", recipe)
        self.assertNotIn("sudo -u", recipe)
        self.assertNotIn("gway-exec", recipe)
        self.assertNotIn("gway-relay", recipe)

    def test_ssh_directory_rejects_group_and_world_permissions(self):
        recipe = RECIPE.read_text()
        self.assertIn("stat.isdir | default(false)", recipe)
        self.assertIn("stat.islnk | default(false)", recipe)
        self.assertIn("stat.pw_name == gway_remote_runner_user", recipe)
        self.assertRegex(recipe, r"stat.mode.*% 8.*== 0")
        self.assertIn("// 8", recipe)


if __name__ == "__main__":
    unittest.main()
