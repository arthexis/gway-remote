import json
import os
from pathlib import Path

import pytest

from gway_remote.mcp_installed_providers import discover_installed_providers


def test_empty_installation(tmp_path):
    assert discover_installed_providers(str(tmp_path / "missing")) == ()


def test_discover_and_remove(tmp_path):
    # Root-owned installation paths are mandatory in production.
    if os.geteuid() != 0:
        pytest.skip("requires root-owned test fixture")
    executable = tmp_path / "provider"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    manifest = tmp_path / "odoo.json"
    manifest.write_text(json.dumps({
        "source_id": "odoo",
        "revision": "a" * 40,
        "executable": str(executable),
        "argv": [str(executable), "--stdio"],
    }))
    result = discover_installed_providers(str(tmp_path))
    assert len(result) == 1
    assert result[0].source_id == "odoo"
    manifest.unlink()
    assert discover_installed_providers(str(tmp_path)) == ()


def test_reject_writable_directory(tmp_path):
    tmp_path.chmod(0o777)
    with pytest.raises(ValueError, match="untrusted provider installation"):
        discover_installed_providers(str(tmp_path))
