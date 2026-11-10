"""Offline contract tests for scoped MCP file downloads."""
import base64
import hashlib
from unittest.mock import Mock

import pytest

from gway_remote.mcp_bridge_gateway_dispatch import OPERATIONS, dispatch_node_tool
from gway_remote.mcp_bridge_contract import validate_envelope, InvalidBridgeRequest
from gway_remote.mcp_bridge_session import SessionBridgeDispatch
from gway_remote.mcp_bearer_gateway import NODE_TOOLS
from gway_remote.node_file_export import CHUNK_BYTES, MAX_FILE_BYTES, export_chunk


def test_contract():
    assert MAX_FILE_BYTES == 1024 * 1024
    assert CHUNK_BYTES == 8192
    assert OPERATIONS["node_file_download"] == ("file.read", "gway:read")
    tool = next(t for t in NODE_TOOLS if t["name"] == "node_file_download")
    assert tool["_meta"]["securitySchemes"][0]["scopes"] == ["gway:read"]


def test_export_roundtrip(tmp_path):
    data = bytes(range(256)) * 400
    (tmp_path / "sample.opus").write_bytes(data)
    pieces, offset = [], 0
    while True:
        chunk = export_chunk("sample.opus", export_root=str(tmp_path), offset=offset)
        pieces.append(base64.b64decode(chunk["content"]))
        assert chunk["sha256"] == hashlib.sha256(data).hexdigest()
        if chunk["next_offset"] is None:
            break
        offset = chunk["next_offset"]
    assert b"".join(pieces) == data


def test_session_scope_and_binding():
    verifier = Mock()
    verifier.verify.return_value = True
    transport = Mock()
    transport.invoke.side_effect = lambda payload: {
        "node": payload["node"], "request_id": payload["request_id"],
        "result": {"content": "YWJj", "size": 3}}
    execution = Mock()
    execution.relay.transport = transport
    session = SessionBridgeDispatch(
        verifier=verifier, session_token="trusted", allowed_node=lambda t, n: n == "gway-001",
        read_principal=lambda t: "reader", execution=execution)
    envelope = {"audience": "gway-001", "scope": "gway:read",
                "principal": "reader", "operation": "file.read",
                "arguments": {"node": "gway-001", "filename": "sample.opus", "offset": 0}}
    assert session(envelope)["size"] == 3
    with pytest.raises(PermissionError):
        session({**envelope, "scope": "gway:execute"})
    with pytest.raises(PermissionError):
        session({**envelope, "principal": "other"})
    with pytest.raises(PermissionError):
        session({**envelope, "arguments": {**envelope["arguments"], "node": "gway-002"}})


def test_dispatch_denies_paths_before_bridge():
    kwargs = dict(socket_path="/nonexistent", key=b"k" * 32, session_id="x" * 48,
                  audience="gway-001", principal="reader", name="node_file_download")
    for filename in ("../etc/passwd", "subdir/file", "/etc/passwd", "..", ""):
        with pytest.raises(ValueError):
            dispatch_node_tool(**kwargs, arguments={
                "node": "gway-001", "filename": filename, "offset": 0})
    with pytest.raises(PermissionError):
        dispatch_node_tool(**kwargs, arguments={
            "node": "gway-002", "filename": "sample.opus", "offset": 0})


def test_session_rejects_mismatched_ssh_receipt():
    verifier = Mock()
    verifier.verify.return_value = True
    execution = Mock()
    execution.relay.transport.invoke.return_value = {
        "node": "gway-001", "request_id": "0" * 32, "result": {"size": 3}}
    session = SessionBridgeDispatch(
        verifier=verifier, session_token="trusted",
        allowed_node=lambda token, node: True,
        read_principal=lambda token: "reader", execution=execution)
    with pytest.raises(PermissionError, match="uncorrelated"):
        session({"audience": "gway-001", "scope": "gway:read",
                 "principal": "reader", "operation": "file.read",
                 "arguments": {"node": "gway-001", "filename": "audio.opus", "offset": 0}})


def test_signed_bridge_envelope_read_only():
    envelope = {
        "version": 1, "request_id": "a" * 32, "principal": "reader",
        "audience": "gway-001", "operation": "file.read",
        "scope": "gway:read", "issued_at": 100, "expires_at": 130,
        "arguments": {"node": "gway-001", "filename": "audio.opus", "offset": 0}}
    assert validate_envelope(envelope, audience="gway-001", now=101) == envelope
    with pytest.raises(InvalidBridgeRequest):
        validate_envelope({**envelope, "scope": "gway:execute"},
                          audience="gway-001", now=101)
    with pytest.raises(InvalidBridgeRequest):
        validate_envelope({**envelope, "audience": "gway-002"},
                          audience="gway-001", now=101)
