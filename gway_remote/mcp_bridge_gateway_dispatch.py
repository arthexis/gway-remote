"""Map authenticated gateway MCP node tools onto the signed private bridge."""
from __future__ import annotations

import secrets
import time

from .mcp_bridge_transport import call_unix
from .node_exec_worker import validate_request_id

CONTROL_AUDIENCE = "gway-000"  # Reserved control-plane envelope, never a satellite.

OPERATIONS = {
    "node_list": ("inventory.list", "gway:read"),
    "node_file_download": ("file.read", "gway:read"),
    "workspace_inspect": ("workspace.inspect", "gway:read"),
    "node_capabilities": ("inventory.capabilities", "gway:read"),
    "node_exec_preview": ("execution.preview", "gway:read"),
    "node_deploy_discovery": ("deployment.discovery", "gway:read"),
    "node_deploy_preview": ("deployment.preview", "gway:read"),
    "node_exec": ("execution.start", "gway:execute"),
    "node_result": ("execution.result", "gway:execute"),
    "node_cancel": ("execution.cancel", "gway:execute"),
    "node_deploy": ("deployment.start", "gway:execute"),
    "node_deploy_status": ("deployment.status", "gway:execute"),
}


def resolve_bridge_audience(name, arguments, *, execution, principal):
    """Bind a gateway tool to a trusted target before session registration.

    Result/cancel destinations come ONLY from the durable owned job receipt.
    No caller-provided address, SSH identity or result target is accepted.
    """
    if name not in OPERATIONS or type(arguments) is not dict:
        raise ValueError("invalid bridge operation")
    if name in {"node_list", "node_capabilities"}:
        return CONTROL_AUDIENCE
    if name in {"node_result", "node_cancel", "node_deploy_status"}:
        if execution is None:
            raise PermissionError("execution unavailable")
        validate_request_id(arguments.get("request_id"))
        receipt = execution._owned(principal, arguments["request_id"])
        node = receipt["node"]
        if "node" in arguments and arguments["node"] != node:
            raise PermissionError("request target differs from owned receipt")
    else:
        node = arguments.get("node")
    from .mcp_bridge_contract import NODE
    if type(node) is not str or not NODE.fullmatch(node) or node == CONTROL_AUDIENCE:
        raise PermissionError("invalid or unbound node target")
    return node


def dispatch_node_tool(*, socket_path, key, session_id, audience, principal,
                       name, arguments):
    if name not in OPERATIONS or type(arguments) is not dict:
        raise ValueError("unsupported bridge tool")
    operation, scope = OPERATIONS[name]
    if audience == CONTROL_AUDIENCE:
        if name not in {"node_list", "node_capabilities"}:
            raise PermissionError("control-plane audience cannot dispatch node operations")
    elif "node" in arguments and arguments["node"] != audience:
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
    if name in {"node_exec", "node_deploy", "node_deploy_status", "node_result", "node_cancel"}:
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
                       require_signed_reply=name in {"node_exec", "node_result", "node_cancel", "workspace_inspect", "node_deploy_preview", "node_deploy_discovery", "node_file_download", "node_deploy", "node_deploy_status"})
    if name in {"node_exec", "node_deploy", "node_deploy_status"}:
        if (type(result) is not dict or
                result.get("request_id") != arguments["request_id"] or
                result.get("node") != audience):
            raise PermissionError("uncorrelated execution response")
    return result
