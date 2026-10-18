"""Static contract checks for the appliance health timer installation."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_health_service_uses_runner_snapshot_and_source():
    service = (ROOT / "deploy/systemd/gway-remote-health.service").read_text()
    assert "User=arthe" in service
    assert "PYTHONPATH=/opt/gway-remote" in service
    assert "GWAY_REMOTE_GITHUB_HEALTH_SNAPSHOT=/home/arthe/.local/state/gway-remote/github-health.json" in service
    assert "EnvironmentFile=/home/arthe/.config/gway-remote/github-health.env" in service


def test_installer_checks_private_token_and_runner_readability():
    tasks = (ROOT / "ansible/roles/gway_remote/tasks/main.yml").read_text()
    assert "github_health_token_config.stat.pw_name == gway_remote_runner_user" in tasks
    assert "github_health_token_config.stat.mode == '0600'" in tasks
    assert "github_health_token_config.stat.isreg | default(false)" in tasks
    assert "Verify API snapshot path is readable by appliance runner" in tasks
    assert 'become_user: "{{ gway_remote_runner_user }}"' in tasks
