"""Ansible B2a installation gate: no live executor or implied activation."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
DEFAULTS = ROOT / "ansible/roles/gway_remote/defaults/main.yml"
MAIN = ROOT / "ansible/roles/gway_remote/tasks/main.yml"
PREPARE = ROOT / "ansible/roles/gway_remote/tasks/node-exec-prepare.yml"
WORKER = ROOT / "gway_remote/node_exec_worker.py"


class ExecutorPreparationTests(unittest.TestCase):
    def test_managed_node_converges_without_user_flags(self):
        defaults = DEFAULTS.read_text()
        main = MAIN.read_text()
        self.assertNotIn("exec_prepare:", defaults)
        self.assertNotIn("exec_enable:", defaults)
        self.assertIn("node-exec-prepare.yml", main)
        self.assertIn("when: ansible_hostname is match('^gway-[0-9]{3,}

    def test_account_locked_unprivileged_with_private_storage(self):
        task = PREPARE.read_text()
        for text in ("ansible.builtin.user:", "password_lock: true",
                     "shell: /usr/sbin/nologin", "create_home: false",
                     'groups: ""', "append: false", 'mode: "0700"',
                     "gway_remote_exec_groups.stdout.split() == [gway_remote_exec_user]",
                     "gway_remote_exec_user != 'root'"):
            with self.subTest(value=text):
                self.assertIn(text, task)

    def test_no_implicit_linger_or_network_activation(self):
        task = PREPARE.read_text()
        self.assertNotIn("when: exec_enable", task)
        self.assertIn("loginctl, enable-linger", task)
        self.assertNotIn("ansible.builtin.systemd:", task)
        self.assertNotIn("authorized_key", task)
        self.assertNotIn("sudoers.d", task)
        self.assertNotIn("gway:execute", task)

    def test_standalone_bootstrap_prepares_dormant_account(self):
        bootstrap = (ROOT / "gway_remote/wireguard_satellite.py").read_text()
        self.assertIn("def prepare_dormant_executor(", bootstrap)
        self.assertIn("result.update(prepare_dormant_executor())", bootstrap)
        self.assertIn('"execution_enabled": False', bootstrap)
        self.assertIn('"loginctl", "enable-linger"', bootstrap)
        self.assertIn("if not args.repair_host_identity:", bootstrap)

    def test_worker_imports_from_root_owned_install_tree(self):
        worker = WORKER.read_text()
        self.assertIn("--setenv=PYTHONPATH=/opt/gway-remote", worker)
        self.assertIn("--working-directory=/var/lib/gway-exec", worker)
        self.assertIn('"/bin/sh", "-c", row["command"]', worker)


if __name__ == "__main__":
    unittest.main()
)", main)

    def test_account_locked_unprivileged_with_private_storage(self):
        task = PREPARE.read_text()
        for text in ("ansible.builtin.user:", "password_lock: true",
                     "shell: /usr/sbin/nologin", "create_home: false",
                     'groups: ""', "append: false", 'mode: "0700"',
                     "gway_remote_exec_groups.stdout.split() == [gway_remote_exec_user]",
                     "gway_remote_exec_user != 'root'"):
            with self.subTest(value=text):
                self.assertIn(text, task)

    def test_no_implicit_linger_or_network_activation(self):
        task = PREPARE.read_text()
        self.assertIn("when: exec_enable | bool", task)
        self.assertIn("loginctl, enable-linger", task)
        self.assertNotIn("ansible.builtin.systemd:", task)
        self.assertNotIn("authorized_key", task)
        self.assertNotIn("sudoers.d", task)
        self.assertNotIn("gway:execute", task)

    def test_worker_imports_from_root_owned_install_tree(self):
        worker = WORKER.read_text()
        self.assertIn("--setenv=PYTHONPATH=/opt/gway-remote", worker)
        self.assertIn("--working-directory=/var/lib/gway-exec", worker)
        self.assertIn('"/bin/sh", "-c", row["command"]', worker)


if __name__ == "__main__":
    unittest.main()
