"""No side-effect tests of the bounded local bootstrap playbook (#641)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "ansible/bootstrap-node.yml"


def test_bounded_bootstrap_reuses_audited_tasks_not_full_role():
    text = BOOTSTRAP.read_text()
    for path in ("node-exec-prepare.yml", "node-exec-select.yml", "node-exec-relay.yml"):
        assert "roles/gway_remote/tasks/" + path in text
    assert "install-package-archive.py" in text
    assert "resolve-executor-user.py" in text
    assert "gway_bootstrap_revision" in text
    assert "gway_bootstrap_source_sha.stdout == gway_bootstrap_revision" in text
    assert "gway_bootstrap_dirty.stdout | trim == ''" in text
    assert "ansible_hostname == gway_bootstrap_node" in text
    assert "gway_exec_relay_public_key is match(" in text
    assert text.index("Verify the pinned local Git revision") < text.index("Install exact reviewed")
    assert text.index("Resolve persistent executor identity") < text.index("Converge selected user manager")
    assert text.index("Install exact reviewed") < text.index("Install existing restricted SSH relay")


def test_bootstrap_does_not_turn_on_unrelated_privileges_or_treat_ack_as_ready():
    content = BOOTSTRAP.read_text()
    assert "watchtower_grant: false" in content
    assert "remote_execution_verified: false" in content
    assert "provider" not in content.lower().split("  tasks:", 1)[1]
    assert "gway_mcp_sources" not in content
    assert "ansible.builtin.include_role" not in content
    assert "host-keyscan" not in content
    assert "shell:" not in content
    assert "sudo -u root" not in content

def test_bounded_playbook_is_checked_by_both_supported_ansible_ci_jobs():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert workflow.count("ansible-playbook --syntax-check -i 'localhost,' ansible/bootstrap-node.yml") == 2
    assert workflow.count("ansible-playbook --syntax-check -i 'localhost,' ansible/playbooks/watchtower-enrollment-refresh.yml") == 2
