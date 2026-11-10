"""Map authenticated gateway MCP node tools onto the signed private bridge."""
from __future__ import annotations

import secrets
import time

from .mcp_bridge_transport import call_unix
from .node_exec_worker import validate_request_id

OPERATIONS = {
    "node_list": ("inventory.list", "gway:read"),
    "node_file_download": ("file.read", "gway:read"),
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
    if name == "node_file_download":
        if (set(arguments) != {"node", "filename", "offset"}
                or type(arguments["filename"]) is not str
                or not arguments["filename"] or len(arguments["filename"]) > 255
                or "/" in arguments["filename"] or arguments["filename"] in {".", ".."}
                or type(arguments["offset"]) is not int
                or not 0 <= arguments["offset"] <= 1024 * 1024):
            raise ValueError("invalid file download arguments")
    if name == "node_list" and arguments != {}:
        raise ValueError("node_list takes no arguments")
    if name == "node_exec":
        validate_request_id(arguments.get("request_id"))
    now = int(time.time())
    envelope = {
        "version": 1, "request_id": secrets.token_hex(16),
        "principal": principal, "audience": audience,
        "operation": operation, "scope": scope,
        "issued_at": now, "expires_at": now + 30,
        "arguments": arguments,
    }
    result = call_unix(socket_path, key, envelope, session_id=session_id,
                       require_signed_reply=name in {"node_exec", "workspace_inspect", "node_deploy_preview", "node_file_download"})
    if name == "node_exec":
        if (type(result) is not dict or
                result.get("request_id") != arguments["request_id"] or
                result.get("node") != audience):
            raise PermissionError("uncorrelated execution response")
    return result
