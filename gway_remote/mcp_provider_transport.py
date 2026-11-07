"""Bounded provider-only RPC over an independently pinned SSH forced command.

This adapter is separate from shell execution. The SSH key MUST be restricted
on the node to gway-provider-protocol-v1; the command argument is not trusted.
"""
import json
import secrets
import subprocess

from .watchtower_exec_transport import pinned_transport

MAX_PROVIDER_REQUEST = 65536
MAX_PROVIDER_REPLY = 262144


class ProviderTransport:
    def __init__(self, execution_transport, *, run=subprocess.run):
        self.execution_transport = execution_transport
        self._run = run

    def invoke(self, node, request, *, trusted_scope):
        if trusted_scope not in ("read", "execute"):
            raise PermissionError("invalid provider scope")
        if type(request) is not dict or request.get("operation") not in ("provider_list", "provider_call"):
            raise ValueError("invalid provider operation")
        fields = ({"operation"} if request["operation"] == "provider_list"
                  else {"operation", "provider", "tool", "arguments"})
        if set(request) != fields:
            raise ValueError("invalid provider request fields")
        if request["operation"] == "provider_call" and type(request["arguments"]) is not dict:
            raise ValueError("invalid arguments")
        pinned = pinned_transport(self.execution_transport, node).node
        request_id = secrets.token_hex(16)
        envelope = {"node": node, "request_id": request_id,
                    "request": request}
        raw = json.dumps(envelope, separators=(",", ":"), allow_nan=False).encode()
        if len(raw) > MAX_PROVIDER_REQUEST:
            raise ValueError("provider request too large")
        argv = ["ssh", "-F", "/dev/null", "-T", "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=yes", "-o", "IdentitiesOnly=yes",
                "-o", "ProxyCommand=none", "-o", "ClearAllForwardings=yes",
                "-o", "PermitLocalCommand=no", "-o", "ConnectTimeout=5",
                "-o", "ConnectionAttempts=1",
                "-o", "UserKnownHostsFile=" + str(pinned.known_hosts),
                "-o", "HostKeyAlias=" + pinned.ssh_host_alias,
                "-i", str(pinned.identity_file), "-l", pinned.remote_user,
                pinned.wireguard_address, "gway-provider-protocol-v1"]
        completed = self._run(argv, input=raw, capture_output=True, timeout=30, check=True)
        if len(completed.stdout) > MAX_PROVIDER_REPLY:
            raise ValueError("provider response too large")
        response = json.loads(completed.stdout)
        if (type(response) is not dict or set(response) != {"node", "request_id", "result"}
                or response["node"] != node or response["request_id"] != request_id):
            raise ValueError("provider identity mismatch")
        return response["result"]
