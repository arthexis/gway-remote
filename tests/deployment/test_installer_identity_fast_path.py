"""Regression: installer fast-path must not switch Linux identity."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class InstallerIdentityFastPathTests(unittest.TestCase):
    def test_worker_probe_refuses_mismatched_installed_identity(self):
        source = (ROOT / "deploy.sh").read_text()
        start = source.index("verify_node_worker_import() {")
        end = source.index("\n}\n", start)
        body = source[start:end]
        self.assertIn('[ "$selected" = "$(id -un)" ] || return 1', body)
        self.assertNotIn("sudo -n -u", body)
        self.assertIn("env PYTHONPATH=/opt/gway-remote", body)

    def test_deployment_passes_invoking_user_not_a_default(self):
        source = (ROOT / "deploy.sh").read_text()
        self.assertIn('-e "gway_remote_runner_user=$(id -un)"', source)
        self.assertIn('if [ "$(id -u)" -eq 0 ]; then', source)


if __name__ == "__main__":
    unittest.main()
