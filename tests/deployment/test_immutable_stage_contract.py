"""Contract for opt-in immutable stage-only GWay Remote release migration."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
STAGE = ROOT / "ansible/playbooks/stage-release.yml"


class RemoteImmutableStageContract(unittest.TestCase):
    def test_stage_playbook_syntax(self):
        if not shutil.which("ansible-playbook"):
            self.skipTest("Ansible not installed")
        result = subprocess.run(
            ["ansible-playbook", "--syntax-check", "-i", "localhost,", str(STAGE)],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_stage_is_isolated_from_live_deployment(self):
        source = STAGE.read_text()
        self.assertIn("/opt/gway-remote", source)
        self.assertIn('releases/{{ remote_stage_commit.stdout }}', source)
        self.assertIn("ansible.builtin.tempfile", source)
        self.assertIn("ansible.builtin.copy", source)
        self.assertIn("ansible.builtin.slurp", source)
        self.assertIn("zipapp", source)
        self.assertIn("REVISION", source)
        self.assertIn("mv, -T, --", source)
        for forbidden in (
            "/usr/local/bin/gway-remote", "state: restarted",
            "systemd_service", "daemon_reload", "systemctl",
            "current", "previous", "/etc/gway-remote/",
            "gway-remote-mobile-api.service", "gway-remote-watch.timer",
        ):
            self.assertNotIn(forbidden, source)

    def test_staging_is_explicit_and_default_deploy_is_preserved(self):
        wrapper = (ROOT / "deploy.sh").read_text()
        self.assertIn("--stage-release", wrapper)
        self.assertIn("flock -n 9", wrapper)
        self.assertIn("ansible/playbooks/stage-release.yml", wrapper)
        self.assertIn('ansible-playbook "$ROOT/ansible/playbook.yml"', wrapper)
        self.assertIn("deployed-commit", wrapper)
        result = subprocess.run(["sh", "-n", str(ROOT / "deploy.sh")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_cli_and_api_provisioning_unchanged(self):
        source = (ROOT / "ansible/roles/gway_remote/tasks/main.yml").read_text()
        self.assertIn("scripts/install-cli.sh", source)
        self.assertIn("/usr/local/bin/gway-remote", source)
        self.assertNotIn("stage-release.yml", source)
        workflow = (ROOT / ".github/workflows/deploy-backend.yml").read_text()
        self.assertIn('["sh", "deploy.sh"]', workflow)
        self.assertNotIn("--stage-release", workflow)


if __name__ == "__main__":
    unittest.main()
