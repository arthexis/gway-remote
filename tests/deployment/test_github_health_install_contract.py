"""Static contract checks for appliance health timer installation."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class GithubHealthInstallContractTests(unittest.TestCase):
    def test_health_service_uses_runner_snapshot_and_source(self):
        service = (ROOT / "deploy/systemd/gway-remote-health.service").read_text()
        self.assertIn("User=arthe", service)
        self.assertIn("PYTHONPATH=/opt/gway-remote", service)
        self.assertIn("GWAY_REMOTE_GITHUB_HEALTH_SNAPSHOT=/home/arthe/.local/state/gway-remote/github-health.json", service)
        self.assertIn("EnvironmentFile=/home/arthe/.config/gway-remote/github-health.env", service)

    def test_installer_checks_private_token_and_runner_readability(self):
        tasks = (ROOT / "ansible/roles/gway_remote/tasks/main.yml").read_text()
        self.assertIn("github_health_token_config.stat.pw_name == gway_remote_runner_user", tasks)
        self.assertIn("github_health_token_config.stat.mode == '0600'", tasks)
        self.assertIn("github_health_token_config.stat.isreg | default(false)", tasks)
        self.assertIn("Verify API snapshot path is readable by appliance runner", tasks)
        self.assertIn('become_user: "{{ gway_remote_runner_user }}"', tasks)


if __name__ == "__main__":
    unittest.main()
