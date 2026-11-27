"""Canonical routing primitives; not yet wired into the active gateway."""
from copy import deepcopy

from .mcp_federated_catalog import FederationError
from .mcp_tool_scope import required_scope
from .node_exec_contract import RELAY_ONLY_NODE


def canonical_node_index(declarations, routes):
    """Group already authenticated, validated routes by operation and node."""
    contracts = {}
    index = {}
    for declaration in declarations:
        alias = declaration["name"]
        if alias not in routes:
            continue
        route = routes[alias]
        node, source, operation, scope = route[:4]
        name = source + "__" + operation
        schema = declaration["inputSchema"]
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if type(properties) is not dict or type(required) is not list:
            raise FederationError("invalid_tool_schema")
        if "node" in properties or "node" in required:
            raise FederationError("reserved_routing_argument")
        if scope != required_scope(declaration):
            raise FederationError("incompatible_tool_scope")
        signature = (source, operation, schema, declaration.get("annotations"), scope)
        if name in contracts and contracts[name][0] != signature:
            raise FederationError("incompatible_tool_contract")
        if name not in contracts:
            public = deepcopy(declaration)
            public["name"] = name
            public_schema = public["inputSchema"]
            public_schema.setdefault("properties", {})["node"] = {
                "type": "string", "description": "Registered target node ID",
                "pattern": "^[a-z][a-z0-9-]{1,63}$",
            }
            if scope == "execute":
                public_schema.setdefault("required", []).append("node")
            contracts[name] = (signature, public)
            index[name] = {}
        if node in index[name]:
            raise FederationError("ambiguous_provider")
        index[name][node] = route
    return [contracts[name][1] for name in sorted(contracts)], index


def resolve_node_route(index, name, arguments, *, legacy_read_node=None):
    """Resolve a canonical call without mutating args or falling back."""
    if type(arguments) is not dict or name not in index:
        raise FederationError("invalid_provider_call")
    candidates = index[name]
    downstream = dict(arguments)
    if "node" in downstream:
        node = downstream.pop("node")
    else:
        node = legacy_read_node
        if type(node) is not str or node not in candidates or candidates[node][3] != "read":
            raise FederationError("node_required")
    if type(node) is not str or node not in candidates:
        raise FederationError("node_route_unavailable")
    return candidates[node], downstream


def canonical_catalog(builtins, declarations, routes, *, legacy_aliases=True):
    """Project canonical public operations and optionally pinned old aliases."""
    from .mcp_catalog import compose_catalog
    public, index = canonical_node_index(declarations, routes)
    projected = {}
    for name, candidates in index.items():
        # Scope is identical for every candidate by contract validation.
        representative = candidates.get("gway-001") or next(iter(candidates.values()))
        projected[name] = (*representative, candidates)
    for alias, route in routes.items():
        if alias in index and route[1] + "__" + route[2] != alias:
            raise FederationError("ambiguous_public_alias")
    aliases = []
    if legacy_aliases:
        for tool in declarations:
            name = tool["name"]
            if name not in routes:
                continue
            if name in index or routes[name][0] == RELAY_ONLY_NODE:
                # ABB has no historic aliases to preserve. Its first provider
                # rollout exposes only canonical names with explicit routing.
                continue
            pinned = deepcopy(tool)
            pinned["inputSchema"].setdefault("properties", {})["node"] = {
                "type": "string", "enum": [routes[name][0]],
            }
            aliases.append(pinned)
            projected[name] = (*routes[name], {routes[name][0]: routes[name]}, "alias")
    return compose_catalog(builtins, public, aliases), projected


def selected_route(route, name, arguments):
    """Select from the exact discovery snapshot; old mode stays unchanged."""
    if len(route) < 6:
        return route, arguments
    if len(route) > 6 and route[6] == "alias":
        downstream = dict(arguments)
        if "node" in downstream and downstream.pop("node") != route[0]:
            raise FederationError("alias_node_mismatch")
        return route[5][route[0]], downstream
    return resolve_node_route({name: route[5]}, name, arguments,
                              legacy_read_node="gway-001")
