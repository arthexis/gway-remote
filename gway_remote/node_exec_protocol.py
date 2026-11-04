"""Narrow JSON-over-stdin node protocol for a future SSH forced command.

Not installed in authorized_keys and not reachable through MCP. Must run under
the existing locked-down gway-exec identity, via an explicitly reviewed
forced-command setup; never execute arbitrary SSH_ORIGINAL_COMMAND.
"""
import json
import os
import socket
import sys

from .node_exec_worker import Jobs, require_account, validate_request_id
from .node_exec_contract import validate_command

MAX_REQUEST_BYTES = 8192
OPERATIONS = {
    "submit": frozenset({"operation", "node", "request_id", "command"}),
    "result": frozenset({"operation", "node", "request_id", "cursor"}),
    "cancel": frozenset({"operation", "node", "request_id"}),
}


def serve_one(raw, *, jobs=None, hostname=None):
    """One message per process, no interactive shell or arbitrary Python calls."""
    require_account()
    if type(raw) is not bytes or len(raw) > MAX_REQUEST_BYTES:
        raise ValueError("oversized request")
    try:
        req = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("invalid request JSON") from None
    if type(req) is not dict or req.get("operation") not in OPERATIONS:
        raise ValueError("invalid operation")
    op = req["operation"]
    if set(req) != OPERATIONS[op]:
        raise ValueError("invalid request fields")
    host = hostname if hostname is not None else socket.gethostname()
    if host != "gway-001" or req["node"] != host:
        raise PermissionError("unapproved node")
    rid = validate_request_id(req["request_id"])
    if jobs is None:
        jobs = Jobs()
    if op == "submit":
        validate_command(host, req["command"])
        jobs.submit(host, req["command"], request_id=rid)
        return {"node": host, "request_id": rid, "status": "accepted"}
    if op == "result":
        cursor = req["cursor"]
        if type(cursor) is not int or cursor < 0:
            raise ValueError("invalid cursor")
        result = jobs.result(rid, cursor)
        if result["node"] != host:
            raise PermissionError("job belongs to another node")
        return result
    row = jobs.row(rid)
    if row["node"] != host:
        raise PermissionError("job belongs to another node")
    return {"node":host, "request_id":rid, "status":jobs.cancel(rid)}


def main():
    # SSH dispatch is not enabled by installing this module. When connected to
    # SSH, the operator must independently bind a fixed, dedicated key to this
    # module and restrict forwarding, PTY and environment.
    try:
        result = serve_one(sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1))
        print(json.dumps(result, separators=(",", ":")))
        return 0
    except (ValueError, PermissionError, RuntimeError, OSError):
        # Never return raw command, stderr secrets, filesystem paths or tokens.
        print(json.dumps({"error":"node operation rejected"}, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    sys.exit(main())
