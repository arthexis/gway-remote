"""Watchtower enrollment deployment stays separate from satellite/bootstrap flows."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_auto_deploy_refreshes_only_existing_watchtower_enrollment():
    script = (ROOT / "scripts/watchtower-auto-deploy.sh").read_text()
    assert "watchtower-enrollment-refresh.yml" in script
    assert script.index("watchtower-mcp.yml") < script.index("watchtower-enrollment-refresh.yml")
    play = (ROOT / "ansible/playbooks/watchtower-enrollment-refresh.yml").read_text()
    assert "hosts: localhost" in play
    assert "Refuse to provision a new enrollment owner" in play
    assert "Require already-enabled enrollment service" in play
    assert "127.0.0.1" in play
    assert "when: enrollment_code.changed" in play
    assert "register(" not in play
    assert "bootstrap_sessions" not in play
    assert "watchtower-enrollment-production.yml" not in script
