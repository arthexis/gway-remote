import json
from pathlib import Path

import pytest

from gway_remote.mcp_installed_providers import discover_installed_providers


def test_empty_installation(tmp_path):
    assert discover_installed_providers(str(tmp_path / "missing")) == ()


def test_discover_and_remove(tmp_path, monkeypatch):
    # Emulate root-owned administrative manifest files in unprivileged CI.
    original = Path.lstat
    def root_owned(path):
        info = original(path)
        if path == tmp_path or path.parent == tmp_path and path.suffix == ".json":
            return type("RootStat", (), {"st_uid": 0, "st_mode": info.st_mode, "st_size": info.st_size})()
        return info
    monkeypatch.setattr(Path, "lstat", root_owned)
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
