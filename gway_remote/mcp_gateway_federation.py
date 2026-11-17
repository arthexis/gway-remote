"""Watchtower federation coordinator; never opens or executes local providers.

The caller supplies a transport that is already bound to attested node IDs.
"""
from .mcp_federated_catalog import catalog_from_nodes, route_provider_call, FederationError
import subprocess


class FederatedProviders:
    def __init__(self, *, transport, nodes):
        if not callable(nodes) or not callable(getattr(transport, "invoke", None)):
            raise TypeError("trusted transport and node inventory required")
        self.transport = transport
        self.nodes = nodes

    def discover(self, builtins=()):
        replies = {}
        for node in self.nodes():
            # A transport outage must not hide healthy nodes or gateway tools.
            # Invalid authenticated catalogs are not silently accepted.
            try:
                response = self.transport.invoke(
                    node, {"operation": "provider_list"}, trusted_scope="read")
            except (OSError, TimeoutError, ConnectionError, subprocess.SubprocessError):
                continue
            if type(response) is not dict:
                raise FederationError("invalid_node_reply")
            replies[node] = response
        return catalog_from_nodes(builtins, replies)

    def call(self, name, arguments, *, authorized_scope, routes=None):
        """Dispatch a route already authenticated and classified by the gateway.

        The HTTP gateway may pass the exact routes snapshot used for public OAuth
        admission. Standalone internal callers retain discovery by default.
        The node still validates the live registered tool and read guard.
        """
        if routes is None:
            _, routes = self.discover()
        return route_provider_call(routes, name, arguments,
                                   authorized_scope=authorized_scope,
                                   invoke=self.transport.invoke)


def federated_tool_result(selected):
    """Preserve bounded MCP images; keep all existing text provider output unchanged.

    The gateway historically wraps provider results as JSON text. Only a
    well-formed, single JPEG image travels as actual MCP image content.
    """
    import base64
    import json

    if (type(selected) is dict and type(selected.get("content")) is list
            and any(type(item) is dict and item.get("type") == "image"
                    for item in selected["content"])):
        if set(selected) != {"content"} or len(selected["content"]) != 1:
            raise ValueError("invalid_provider_image")
        item = selected["content"][0]
        if type(item) is not dict or set(item) != {"type", "mimeType", "data"} or (
                item["type"] != "image" or item["mimeType"] != "image/jpeg"
                or type(item["data"]) is not str or len(item["data"]) > 190_000):
            raise ValueError("invalid_provider_image")
        try:
            payload = base64.b64decode(item["data"], validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("invalid_provider_image") from exc
        if not 0 < len(payload) <= 140_000 or not payload.startswith(b"\xff\xd8"):
            raise ValueError("invalid_provider_image")
        return selected
    return {"content": [{"type": "text", "text": json.dumps(selected, separators=(",", ":"))}]}
