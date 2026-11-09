"""Read-only MCP stdio provider for existing GWay Remote diagnostics.

Activation requires an operator-reviewed, root-owned installed-provider manifest.
No shell commands, user-supplied paths, or execution tools are exposed.
"""
import json
import sys

from .hardware_diagnostics import inspect
from .status import status

TOOLS = (
    {"name": "hardware", "description": "Read local hardware/v1 diagnostics",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "destructiveHint": False}},
    {"name": "status", "description": "Read local status/v1 diagnostics",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "destructiveHint": False}},
)


def dispatch(message):
    if type(message) is not dict or message.get("jsonrpc") != "2.0":
        raise ValueError("invalid MCP request")
    method = message.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "gway-fleet-diagnostics", "version": "1"}}
    elif method == "notifications/initialized":
        return None
    elif method == "tools/list":
        result = {"tools": list(TOOLS)}
    elif method == "tools/call":
        params = message.get("params")
        if type(params) is not dict or set(params) != {"name", "arguments"} or params["arguments"] != {}:
            raise ValueError("invalid tool arguments")
        if params["name"] == "hardware":
            report = inspect()
        elif params["name"] == "status":
            report = status(depth="quick")
        else:
            raise ValueError("unknown tool")
        result = {"content": [{"type": "text", "text": json.dumps(report, separators=(",", ":"))}]}
    else:
        raise ValueError("unsupported method")
    return {"jsonrpc": "2.0", "id": message.get("id"), "result": result}


def main():
    for line in sys.stdin.buffer:
        try:
            if len(line) > 65536:
                raise ValueError("oversized request")
            reply = dispatch(json.loads(line))
        except (ValueError, TypeError, OSError):
            reply = {"jsonrpc": "2.0", "id": None,
                     "error": {"code": -32602, "message": "invalid request"}}
        if reply is not None:
            sys.stdout.write(json.dumps(reply, separators=(",", ":")) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
