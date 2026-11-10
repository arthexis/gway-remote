"""Opt-in startup of the gateway's local bridge."""
import os
import threading
from pathlib import Path

from .mcp_bridge_sessions import BridgeSessions
from .mcp_bridge_server import serve_managed_sessions


def start_bridge(verifier, execution=None, *, read_transport=None):
    if os.environ.get("GWAY_MCP_BRIDGE_ENABLED") != "1":
        return None
    key_file = Path(os.environ["GWAY_MCP_BRIDGE_KEY_FILE"])
    socket_path = Path(os.environ["GWAY_MCP_BRIDGE_SOCKET"])
    if not key_file.is_absolute() or not socket_path.is_absolute():
        raise ValueError("absolute bridge paths required")
    if (key_file.is_symlink() or not key_file.is_file()
            or key_file.stat().st_mode & 0o077):
        raise PermissionError("unsafe key permissions")
    key = key_file.read_bytes()
    if len(key) < 32:
        raise ValueError("weak bridge key")

    def principal(token):
        if not (verifier.verify(token, required_scope="gway:read")
                or verifier.verify(token, required_scope="gway:execute")):
            raise PermissionError("invalid bearer")
        parts = token.split("_", 2)
        if len(parts) != 3 or parts[0] != "gwr" or len(parts[1]) != 24:
            raise PermissionError("invalid principal format")
        try:
            int(parts[1], 16)
        except ValueError as exc:
            raise PermissionError("invalid principal format") from exc
        return parts[1]

    sessions = BridgeSessions(
        verifier=verifier, execution=execution,
        allowed_node=lambda token, node: node == "gway-001",
        read_principal=principal, read_transport=read_transport)
    service = serve_managed_sessions(
        socket_path, key=key, audience="gway-001", sessions=sessions)
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    try:
        thread.start()
    except BaseException:
        service.server_close()
        raise
    return service, thread, sessions, (str(socket_path), key, "gway-001")
