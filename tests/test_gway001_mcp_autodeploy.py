"""Guard the gway-001 isolated MCP auto-deployment wiring."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_backend_workflow_converges_isolated_mcp():
    workflow = (ROOT / ".github/workflows/deploy-backend.yml").read_text()
    assert workflow.index("Transactional install, restart and authenticated health") < workflow.index(
        "Converge isolated gway-001 MCP runtime through Ansible")
    assert "ansible/playbooks/gway001-mcp-runtime.yml" in workflow
    assert 'mcp_target_sha=${GITHUB_SHA}' in workflow


def test_mcp_playbook_is_revision_pinned_and_rolls_back():
    playbook = (ROOT / "ansible/playbooks/gway001-mcp-runtime.yml").read_text()
    assert "lookup('pipe', 'hostname -s') == 'gway-001'" in playbook
    assert "mcp_target_sha is match('^[0-9a-f]{40}$')" in playbook
    assert "scripts/stage-mcp-runtime.py" in playbook
    assert "Restore previous immutable release pointer" in playbook
    assert "is-active, --quiet, gway-remote-mcp.service" in playbook
