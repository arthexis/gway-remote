"""Watchtower federation coordinator; never opens or executes local providers.

The caller supplies a transport that is already bound to attested node IDs.
"""
from .mcp_federated_catalog import catalog_from_nodes, route_provider_call


class FederatedProviders:
    def __init__(self, *, transport, nodes):
        if not callable(nodes) or not callable(getattr(transport, "invoke", None)):
            raise TypeError("trusted transport and node inventory required")
        self.transport = transport
        self.nodes = nodes

    def discover(self, builtins=()):
        replies = {}
        for node in self.nodes():
            # Never let an MCP caller choose an arbitrary address or node.
            replies[node] = self.transport.invoke(
                node, {"operation": "provider_list"}, trusted_scope="read")
        return catalog_from_nodes(builtins, replies)

    def call(self, name, arguments, *, authorized_scope):
        _, routes = self.discover()
        return route_provider_call(routes, name, arguments,
                                   authorized_scope=authorized_scope,
                                   invoke=self.transport.invoke)
