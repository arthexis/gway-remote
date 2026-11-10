"""Offline isolation and regression tests for the gway-001 file reader."""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from gway_remote import node_exec_protocol, node_file_reader

RID = "a" * 32


def request(op="file_read", **kwargs):
    return json.dumps({"operation": op, "node": "gway-001",
                       "request_id": RID, "filename": "narracion.opus",
                       "offset": 0, **kwargs}).encode()


def test_file_read_invokes_only_fixed_reader():
    with patch.object(node_exec_protocol, "require_account"), patch.object(
        node_exec_protocol.subprocess, "run"
    ) as run:
        run.return_value = SimpleNamespace(stdout=json.dumps({
            "node": "gway-001", "request_id": RID, "result": {"size": 3}
        }).encode())
        response = node_exec_protocol.serve_one(request(), hostname="gway-001")
        assert response["result"]["size"] == 3
        args, kwargs = run.call_args
        assert args[0] == ["/usr/bin/sudo", "-n", "-u", "gway-exec",
                           "/usr/bin/env", "PYTHONPATH=/opt/gway-remote",
                           "/usr/bin/python3", "-m", "gway_remote.node_file_reader"]
        assert kwargs["timeout"] == 5
        assert kwargs["check"] is True
        assert kwargs["input"] and "shell" not in kwargs


@pytest.mark.parametrize("response", [
    {"node": "gway-002", "request_id": RID, "result": {}},
    {"node": "gway-001", "request_id": "b" * 32, "result": {}},
    {"node": "gway-001", "request_id": RID, "result": {}, "extra": True},
    {"error": "file read rejected"},
])
def test_file_read_rejects_uncorrelated_helper(response):
    with patch.object(node_exec_protocol, "require_account"), patch.object(
        node_exec_protocol.subprocess, "run",
        return_value=SimpleNamespace(stdout=json.dumps(response).encode())
    ):
        with pytest.raises(PermissionError):
            node_exec_protocol.serve_one(request(), hostname="gway-001")


def test_file_read_fails_closed_without_sudoers():
    from subprocess import CalledProcessError
    with patch.object(node_exec_protocol, "require_account"), patch.object(
        node_exec_protocol.subprocess, "run",
        side_effect=CalledProcessError(1, "sudo")
    ):
        with pytest.raises(PermissionError, match="unavailable"):
            node_exec_protocol.serve_one(request(), hostname="gway-001")


def test_other_nodes_do_not_invoke_reader():
    with patch.object(node_exec_protocol, "require_account"), patch.object(
        node_exec_protocol.subprocess, "run"
    ) as run:
        payload = json.loads(request())
        payload["node"] = "gway-002"
        with pytest.raises(PermissionError):
            node_exec_protocol.serve_one(json.dumps(payload).encode(), hostname="gway-002")
        run.assert_not_called()


def test_reader_requires_dedicated_uid():
    with patch.object(node_file_reader.os, "geteuid", return_value=-1):
        with pytest.raises(PermissionError, match="identity"):
            node_file_reader.serve(json.dumps({
                "node": "gway-001", "request_id": RID,
                "filename": "narracion.opus", "offset": 0
            }).encode(), hostname="gway-001")


def test_reader_rejects_extra_fields_and_wrong_node():
    with patch.object(node_file_reader.os, "geteuid", return_value=990), patch.object(
        node_file_reader, "export_chunk"
    ) as export, patch("pwd.getpwnam", return_value=SimpleNamespace(pw_uid=990)):
        for payload in (
            {"node": "gway-001", "request_id": RID, "filename": "narracion.opus",
             "offset": 0, "command": "id"},
            {"node": "gway-002", "request_id": RID, "filename": "narracion.opus",
             "offset": 0},
        ):
            with pytest.raises((ValueError, PermissionError)):
                node_file_reader.serve(json.dumps(payload).encode(), hostname="gway-001")
        export.assert_not_called()


def test_reader_correlates_and_uses_fixed_export_root():
    with patch.object(node_file_reader.os, "geteuid", return_value=990), patch.object(
        node_file_reader, "export_chunk", return_value={"size": 21023}
    ) as export, patch("pwd.getpwnam", return_value=SimpleNamespace(pw_uid=990)):
        response = node_file_reader.serve(json.dumps({
            "node": "gway-001", "request_id": RID,
            "filename": "narracion.opus", "offset": 8192
        }).encode(), hostname="gway-001")
        assert response == {"node": "gway-001", "request_id": RID,
                            "result": {"size": 21023}}
        export.assert_called_once_with("narracion.opus",
                                       export_root="/var/lib/gway-mcp-exports",
                                       offset=8192)
