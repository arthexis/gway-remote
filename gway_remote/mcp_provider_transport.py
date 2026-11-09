"""Provider RPC adapter over the existing pinned Watchtower-to-node SSH channel.

No additional key, listener, or shell execution. OAuth scope is checked by
Watchtower before the request enters this operator-pinned channel.
"""
import secrets

from .watchtower_exec_transport import PinnedNode, pinned_transport


class ProviderTransport:
    def __init__(self, execution_transport, *, read_transport=None, require_read_identity=False):
        self.execution_transport = execution_transport
        self.read_transport = read_transport
        self.require_read_identity = require_read_identity

    def invoke(self, node, request, *, trusted_scope):
        if trusted_scope not in ("read", "execute"):
            raise PermissionError("invalid provider scope")
        if type(request) is not dict or request.get("operation") not in ("provider_list", "provider_call"):
            raise ValueError("invalid provider operation")
        operation = request["operation"]
        if set(request) != ({"operation"} if operation == "provider_list"
                               else {"operation", "provider", "tool", "arguments"}):
            raise ValueError("invalid provider request")
        if operation == "provider_call" and type(request["arguments"]) is not dict:
            raise ValueError("invalid provider arguments")
        payload = {"operation": ("provider_read_call" if operation == "provider_call" and trusted_scope == "read" else operation), "node": node,
                   "request_id": secrets.token_hex(16)}
        if operation == "provider_call":
            payload.update({key: request[key] for key in ("provider", "tool", "arguments")})
            if trusted_scope == "execute":
                payload["authorized_scope"] = trusted_scope
        if trusted_scope == "read":
            if self.read_transport is None and self.require_read_identity:
                raise PermissionError("node has no pinned read identity")
            selected = self.read_transport if self.read_transport is not None else self.execution_transport
        else:
            selected = self.execution_transport
        transport = pinned_transport(selected, node)
        if trusted_scope == "read" and self.read_transport is not None:
            if transport.node.remote_user == pinned_transport(self.execution_transport, node).node.remote_user or \
                    transport.node.identity_file == pinned_transport(self.execution_transport, node).node.identity_file:
                raise PermissionError("read identity must be separate from execute identity")
        if trusted_scope == "read" and self.require_read_identity:
            execute_node = pinned_transport(self.execution_transport, node).node
            read_node = transport.node
            if isinstance(read_node, PinnedNode) and isinstance(execute_node, PinnedNode):
                if (read_node.wireguard_address != execute_node.wireguard_address
                        or read_node.host_key_sha256 != execute_node.host_key_sha256
                        or read_node.ssh_host_alias != execute_node.ssh_host_alias):
                    raise PermissionError("read and execute pin different enrolled hosts")
        response = transport.invoke(payload)
        if (type(response) is not dict or set(response) != {"node", "request_id", "result"}
                or response["node"] != node or response["request_id"] != payload["request_id"]):
            raise ValueError("invalid provider response")
        return response["result"]
