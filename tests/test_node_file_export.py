"""Offline tests for the bounded file export primitive."""
import base64
import hashlib

import pytest

from gway_remote.node_file_export import MAX_FILE_BYTES, export_file


def test_roundtrip(tmp_path):
    payload = b"RIFF" + b"audio" * 10
    (tmp_path / "narracion.wav").write_bytes(payload)
    result = export_file("narracion.wav", export_root=str(tmp_path))
    assert base64.b64decode(result["content"]) == payload
    assert result["size"] == len(payload)
    assert result["sha256"] == hashlib.sha256(payload).hexdigest()
    assert result["mime_type"] == "audio/x-wav"


@pytest.mark.parametrize("name", ["../secret", "subdir/file", "/etc/passwd", ".", "..", ""])
def test_rejects_paths(tmp_path, name):
    with pytest.raises(ValueError):
        export_file(name, export_root=str(tmp_path))


def test_rejects_symlink(tmp_path):
    (tmp_path / "actual").write_bytes(b"ok")
    (tmp_path / "link").symlink_to("actual")
    with pytest.raises(OSError):
        export_file("link", export_root=str(tmp_path))


def test_rejects_large_file(tmp_path):
    with (tmp_path / "large").open("wb") as handle:
        handle.truncate(MAX_FILE_BYTES + 1)
    with pytest.raises(ValueError):
        export_file("large", export_root=str(tmp_path))


def test_rejects_directory(tmp_path):
    (tmp_path / "folder").mkdir()
    with pytest.raises(ValueError):
        export_file("folder", export_root=str(tmp_path))


def test_accepts_exact_limit(tmp_path):
    (tmp_path / "exact").write_bytes(b"x" * MAX_FILE_BYTES)
    assert export_file("exact", export_root=str(tmp_path))["size"] == MAX_FILE_BYTES
