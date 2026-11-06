"""Opt-in startup of the gateway's local bridge."""
import os
import threading
from pathlib import Path

from .mcp_bridge_sessions import BridgeSessions
from .mcp_bridge_server import serve_managed_sessions


def start_bridge(verifier, execution=None):
    if os.environ.get("GWAY_MCP_BRIDGE_ENABLED") != "1":
        return None
    key_file = Path(os.environ["GWAY_MCP_BRIDGE_KEY_FILE"])
    socket_path = Path(os.environ["GWAY_MCP_BRIDGE_SOCKET"])
    if not key_file.is_absolute() or not socket_path.is_absolute():
        raise ValueError("absolute bridge paths required")
    if key_file.is_symlink() or key_file.stat().st_mode & 0o077:
        raise PermissionError("unsafe key permissions")
    key = key_file.read_bytes()
    if len(key) < 32:
        raise ValueError("weak bridge key")

    def principal(token):
        if not (verifier.verify(token, required_scope="gway:read")
                or verifier.verify(token, required_scope="gway:execute")):
            raise PermissionError("invalid bearer")
        return token.split("_", 2)[1]

    sessions = BridgeSessions(
        verifier=verifier, execution=execution,
        allowed_node=lambda token, node: node == "gway-001",
        read_principal=principal)
    service = serve_managed_sessions(
        socket_path, key=key, audience="gway-001", sessions=sessions)
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    return service, thread, sessions, (str(socket_path), key, "gway-001")
