"""Federated MCP catalog boundary: Watchtower accepts node declarations, not local providers.

Transport/authentication is supplied by the caller. This module never launches
a provider, opens a network connection, or selects a node OS account.
"""
import re

from .mcp_catalog import compose_catalog
from .mcp_tool_scope import required_scope

_NODE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
_PROVIDER = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_TOOL = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class FederationError(ValueError):
    pass


def catalog_from_nodes(builtins, node_catalogs):
    """Return (advertised tools, routing table) from authenticated node replies.

    node_catalogs is a mapping keyed by independently authenticated node ID.
    Reject malformed and conflicting tool names rather than trusting a provider
    to override built-ins or another node's tools.
    """
    if type(node_catalogs) is not dict:
        raise FederationError("invalid_node_catalogs")
    routes = {}
    declarations = []
    for node, response in sorted(node_catalogs.items()):
        if type(node) is not str or not _NODE.fullmatch(node) or type(response) is not dict or set(response) != {"node", "providers"} or response["node"] != node or type(response["providers"]) is not list:
            raise FederationError("invalid_node_catalog")
        providers = response["providers"]
        for provider in providers:
            if type(provider) is not dict or not {"provider", "node", "revision", "status", "tools"} <= set(provider) or provider["node"] != node or provider["status"] not in ("available", "unavailable") or type(provider["revision"]) is not str:
                raise FederationError("invalid_provider")
            source = provider["provider"]
            if type(source) is not str or not _PROVIDER.fullmatch(source):
                raise FederationError("invalid_provider")
            if type(provider["tools"]) is not list:
                raise FederationError("invalid_tools")
            if provider["status"] != "available":
                continue
            for tool in provider["tools"]:
                if type(tool) is not dict or type(tool.get("name")) is not str or not _TOOL.fullmatch(tool["name"]):
                    raise FederationError("invalid_tool")
                if type(tool.get("inputSchema")) is not dict:
                    raise FederationError("invalid_tool_schema")
                name = source + "__" + tool["name"]
                if name in routes:
                    raise FederationError("ambiguous_provider")
                routes[name] = (node, source, tool["name"], required_scope(tool))
                declarations.append({**tool, "name": name})
    return compose_catalog(builtins, declarations), routes


def route_provider_call(routes, name, arguments, *, authorized_scope, invoke):
    """Invoke a trusted transport callback with node-owned provider identity.

    invoke(node, request, trusted_scope=...) must authenticate its node peer;
    never derive trusted_scope from untrusted request JSON.
    """
    if type(arguments) is not dict or name not in routes:
        raise FederationError("invalid_provider_call")
    node, provider, tool, scope = routes[name]
    if scope == "execute" and authorized_scope != "execute":
        raise PermissionError("mcp_execute_scope_required")
    if authorized_scope not in ("read", "execute"):
        raise PermissionError("invalid_scope")
    return invoke(node, {"operation": "provider_call", "provider": provider,
                         "tool": tool, "arguments": arguments},
                  trusted_scope=authorized_scope)
