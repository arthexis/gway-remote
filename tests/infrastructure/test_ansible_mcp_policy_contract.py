"""Static contracts for Ansible MCP policy staging.

Runtime idempotence and gateway activation are tested separately.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "ansible/roles/gway_remote/tasks/mcp-source-provision.yml"
ENTRY = ROOT / "ansible/playbooks/validate-mcp-source-provision.yml"
CI = ROOT / ".github/workflows/ci.yml"


def test_policy_tasks_have_single_lifecycle():
    source = TASKS.read_text()
    for name in (
        "Validate MCP source registrations",
        "Validate each pinned read-only MCP provider",
        "Inspect existing policy without following symlinks",
        "Install registration-only MCP policy",
        "Validate staged policy with installed package parser",
        "Compute staged policy checksum",
        "Assert verified digest",
    ):
        assert source.count("- name: " + name) == 1


def test_policy_has_no_secondary_approval_or_automatic_activation():
    source = TASKS.read_text()
    assert "gway_mcp_policy_replace_approved" not in source
    assert "systemd:" not in source
    assert "service:" not in source
    assert "permission == 'read'" in source
    assert "follow: false" in source
    assert "checksum_algorithm: sha256" in source


def test_dynamic_include_is_checked_through_static_import():
    entry = ENTRY.read_text()
    ci = CI.read_text()
    assert "ansible.builtin.import_tasks: ../roles/gway_remote/tasks/mcp-source-provision.yml" in entry
    assert ci.count("ansible/playbooks/validate-mcp-source-provision.yml") >= 2
