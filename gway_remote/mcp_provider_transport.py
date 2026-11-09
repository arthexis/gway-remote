"""Provider RPC adapter over the existing pinned Watchtower-to-node SSH channel.

No additional key, listener, or shell execution. OAuth scope is checked by
Watchtower before the request enters this operator-pinned channel.
"""
import secrets

from .watchtower_exec_transport import pinned_transport


class ProviderTransport:
    def __init__(self, execution_transport):
        self.execution_transport = execution_transport

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
        transport = pinned_transport(self.execution_transport, node)
        response = transport.invoke(payload)
        if (type(response) is not dict or set(response) != {"node", "request_id", "result"}
                or response["node"] != node or response["request_id"] != payload["request_id"]):
            raise ValueError("invalid provider response")
        return response["result"]
