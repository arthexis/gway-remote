"""Static safety contract for the explicit two-host MCP policy rollout."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "ansible" / "playbooks"


def test_rollout_is_explicit_and_backend_first():
    code = (ROOT / "mcp-source-policy-rollout.yml").read_text()
    assert "mcp_policy_approved | default(false) | bool" in code
    assert "rollout_source.stat.checksum == mcp_policy_sha256" in code
    assert "groups.get('mcp_policy_backend', []) | length == 1" in code
    assert "groups.get('mcp_policy_endpoints', []) | length == 1" in code
    assert code.index("import_playbook: mcp-source-policy-backend.yml") < code.index(
        "import_playbook: mcp-source-policy.yml")


def test_backend_preflight_and_dynamic_user_runtime():
    code = (ROOT / "mcp-source-policy-backend.yml").read_text()
    assert "backend_policy_directory.stat.pw_name == 'root'" in code
    assert "backend_service_unit.stat.isreg | default(false)" in code
    assert 'XDG_RUNTIME_DIR: "/run/user/{{ backend_uid.stdout }}"' in code
    assert "/run/user/1000" not in code


def test_gateway_requires_operator_policy_and_service():
    code = (ROOT / "mcp-source-policy.yml").read_text()
    assert "mcp_policy_role == 'gateway'" in code
    assert "mcp_policy_service == 'gway-mcp-gateway.service'" in code
    assert "verified_policy.stat.checksum == mcp_policy_sha256" in code
