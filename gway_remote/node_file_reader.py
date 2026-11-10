"""Single-purpose, fail-closed file reader for the gway-exec identity.

Invoked only by the fixed sudoers command; no shell, arbitrary path or
provider operation is accepted.
"""
import json
import os
import socket
import sys

from .node_exec_worker import validate_request_id
from .node_file_export import export_chunk

MAX_INPUT = 1024


def serve(raw, *, hostname=None):
    import pwd
    if os.geteuid() != pwd.getpwnam("gway-exec").pw_uid:
        raise PermissionError("file reader identity mismatch")
    if type(raw) is not bytes or len(raw) > MAX_INPUT:
        raise ValueError("invalid file reader request")
    request = json.loads(raw)
    if type(request) is not dict or set(request) != {"node", "request_id", "filename", "offset"}:
        raise ValueError("invalid file reader fields")
    node = hostname if hostname is not None else socket.gethostname()
    if node != "gway-001" or request["node"] != node:
        raise PermissionError("file reader node mismatch")
    request_id = validate_request_id(request["request_id"])
    filename, offset = request["filename"], request["offset"]
    if type(filename) is not str or not filename or len(filename) > 255:
        raise ValueError("invalid filename")
    if type(offset) is not int or not 0 <= offset <= 1048576:
        raise ValueError("invalid offset")
    result = export_chunk(filename, export_root="/var/lib/gway-mcp-exports", offset=offset)
    return {"node": node, "request_id": request_id, "result": result}


def main():
    try:
        result = serve(sys.stdin.buffer.read(MAX_INPUT + 1))
        print(json.dumps(result, separators=(",", ":")))
        return 0
    except (ValueError, PermissionError, OSError, TypeError, KeyError):
        print('{"error":"file read rejected"}')
        return 1


if __name__ == "__main__":
    sys.exit(main())
