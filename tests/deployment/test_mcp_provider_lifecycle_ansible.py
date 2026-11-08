"""Ansible lifecycle regression for a disposable node-owned MCP provider."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("ansible-playbook") is None, reason="ansible-core unavailable")
def test_ansible_fixture_lifecycle(tmp_path):
    playbook = Path(__file__).resolve().parents[2] / "ansible/playbooks/test-mcp-provider-lifecycle.yml"
    directory = tmp_path / "providers"

    def converge(version):
        proc = subprocess.run(
            ["ansible-playbook", "-i", "localhost,", str(playbook), "-e",
             json.dumps({"fixture_dir": str(directory), "fixture_version": version})],
            capture_output=True, text=True, timeout=90, check=False,
            env={**os.environ, "ANSIBLE_LOCAL_TEMP": str(tmp_path / "ansible-tmp")})
        assert proc.returncode == 0, proc.stdout + proc.stderr
        return proc.stdout

    assert "changed=2" in converge("v1")
    assert "changed=0" in converge("v1")
    assert "changed=2" in converge("v2")
    assert "changed=0" in converge("v2")
    assert "changed=2" in converge("v1")
    manifest = json.loads((directory / "fixture474.json").read_text())
    assert manifest["revision"] == "a" * 40
    assert "ping_v1" in (directory / "fixture.py").read_text()
    (directory / "fixture474.json").unlink()
    assert not (directory / "fixture474.json").exists()
