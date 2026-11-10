"""Ansible B2a installation gate: no live executor or implied activation."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
DEFAULTS = ROOT / "ansible/roles/gway_remote/defaults/main.yml"
MAIN = ROOT / "ansible/roles/gway_remote/tasks/main.yml"
PREPARE = ROOT / "ansible/roles/gway_remote/tasks/node-exec-prepare.yml"
WORKER = ROOT / "gway_remote/node_exec_worker.py"


class ExecutorPreparationTests(unittest.TestCase):
    def test_normal_install_never_provisions_legacy_executor(self):
        main = MAIN.read_text()
        defaults = DEFAULTS.read_text()
        for name in ("node-exec-prepare.yml", "node-exec-select.yml",
                     "node-exec-relay.yml", "node-mcp-deploy.yml"):
            self.assertNotIn("include_tasks: " + name, main)
        self.assertNotIn("gway_remote_exec_user:", defaults)
        self.assertNotIn("gway_remote_exec_run_user:", defaults)
        self.assertNotIn("gway-exec", defaults)
        self.assertNotIn("gway-relay", defaults)
        self.assertNotIn("sudo -u", main)

    def test_wireguard_bootstrap_does_not_create_executor(self):
        bootstrap = (ROOT / "gway_remote/wireguard_satellite.py").read_text()
        self.assertNotIn("prepare_dormant_executor", bootstrap)
        self.assertNotIn("useradd", bootstrap)
        self.assertNotIn("groupadd", bootstrap)

    def test_worker_imports_from_root_owned_install_tree(self):
        worker = WORKER.read_text()
        self.assertIn("--setenv=PYTHONPATH=/opt/gway-remote", worker)
        # The default account retains its established directory, while the
        # explicitly configured operator uses separate private job storage.
        self.assertIn('"--working-directory=" +', worker)
        self.assertIn('str(self.path.parent)', worker)
        self.assertNotIn('selected_user() == DEFAULT_USER', worker)
        self.assertIn('str(self.path.parent)', worker)
        self.assertIn('"/bin/sh", "-c", row["command"]', worker)


if __name__ == "__main__":
    unittest.main()
