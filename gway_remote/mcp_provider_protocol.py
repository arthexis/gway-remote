"""One-shot provider RPC receiver for a dedicated SSH forced command.

Deployment must bind a dedicated SSH key to this entrypoint with forwarding
disabled. The service runs as the node-selected non-root account. A separate
trusted wrapper supplies the effective scope; never accept scope from stdin.
"""
import json
import os
import socket
import sys

from .mcp_node_providers import dispatch_node_provider_request, NodeProviderError
from .mcp_source_policy import load_source_policy, policy_digest

MAX_REQUEST = 65536


def serve_one(raw, *, registrations, node_id, trusted_scope):
    if os.geteuid() == 0:
        raise PermissionError("root provider execution forbidden")
    if trusted_scope not in ("read", "execute"):
        raise PermissionError("invalid trusted scope")
    if type(raw) is not bytes or len(raw) > MAX_REQUEST:
        raise ValueError("oversized provider request")
    envelope = json.loads(raw)
    if (type(envelope) is not dict or set(envelope) != {"node", "request_id", "request"}
            or envelope["node"] != node_id or type(envelope["request_id"]) is not str
            or len(envelope["request_id"]) != 32):
        raise ValueError("invalid provider envelope")
    result = dispatch_node_provider_request(
        registrations, envelope["request"], node_id=node_id,
        trusted_scope=trusted_scope)
    return {"node": node_id, "request_id": envelope["request_id"], "result": result}


def main():
    # Do not start from a generic shell command or inherit arbitrary scope.
    # This requires a trusted forced-command wrapper to inject a fixed scope.
    scope = os.environ.get("GWAY_PROVIDER_TRUSTED_SCOPE")
    if scope not in ("read", "execute") or os.environ.get("SSH_ORIGINAL_COMMAND") not in (None, ""):
        raise SystemExit(1)
    path = os.environ.get("GWAY_MCP_SOURCE_POLICY")
    if not path:
        raise SystemExit(1)
    try:
        registrations, _ = load_source_policy(path, expected_sha256=policy_digest(path))
        reply = serve_one(sys.stdin.buffer.read(MAX_REQUEST + 1),
                          registrations=registrations, node_id=socket.gethostname(),
                          trusted_scope=scope)
        print(json.dumps(reply, separators=(",", ":")))
        return 0
    except (ValueError, OSError, RuntimeError, PermissionError, NodeProviderError):
        print('{"error":"provider operation rejected"}')
        return 1


if __name__ == "__main__":
    sys.exit(main())
