"""Map authenticated gateway MCP node tools onto the signed private bridge."""
from __future__ import annotations

import secrets
import time

from .mcp_bridge_transport import call_unix

OPERATIONS = {
    "node_list": ("inventory.list", "gway:read"),
    "workspace_inspect": ("workspace.inspect", "gway:read"),
    "node_capabilities": ("inventory.capabilities", "gway:read"),
    "node_exec_preview": ("execution.preview", "gway:read"),
    "node_deploy_preview": ("deployment.preview", "gway:read"),
    "node_exec": ("execution.start", "gway:execute"),
    "node_result": ("execution.result", "gway:execute"),
    "node_cancel": ("execution.cancel", "gway:execute"),
    "node_deploy": ("deployment.start", "gway:execute"),
    "node_deploy_status": ("deployment.status", "gway:execute"),
}


def dispatch_node_tool(*, socket_path, key, session_id, audience, principal,
                       name, arguments):
    if name not in OPERATIONS or type(arguments) is not dict:
        raise ValueError("unsupported bridge tool")
    operation, scope = OPERATIONS[name]
    if "node" in arguments and arguments["node"] != audience:
        raise PermissionError("cross-node dispatch denied")
    if name == "node_list" and arguments != {}:
        raise ValueError("node_list takes no arguments")
    now = int(time.time())
    envelope = {
        "version": 1, "request_id": secrets.token_hex(16),
        "principal": principal, "audience": audience,
        "operation": operation, "scope": scope,
        "issued_at": now, "expires_at": now + 30,
        "arguments": arguments,
    }
    return call_unix(socket_path, key, envelope, session_id=session_id)
