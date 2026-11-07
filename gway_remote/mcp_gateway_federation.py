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

    def call(self, name, arguments, *, authorized_scope):
        _, routes = self.discover()
        return route_provider_call(routes, name, arguments,
                                   authorized_scope=authorized_scope,
                                   invoke=self.transport.invoke)
