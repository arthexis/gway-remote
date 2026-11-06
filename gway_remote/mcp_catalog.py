"""Node-owned MCP catalog composition.

The node, not the public gateway, owns the names and schemas it advertises.
The gateway must never silently override a node tool.
"""
from __future__ import annotations


class ToolCatalogError(ValueError):
    """Invalid or conflicting MCP tool declaration."""


def compose_catalog(*catalogs):
    """Combine local tool catalogs without allowing shadowing or malformed entries."""
    result = []
    names = set()
    for catalog in catalogs:
        if not isinstance(catalog, (list, tuple)):
            raise ToolCatalogError("invalid tool catalog")
        for tool in catalog:
            if not isinstance(tool, dict):
                raise ToolCatalogError("invalid tool declaration")
            name = tool.get("name")
            schema = tool.get("inputSchema")
            if not isinstance(name, str) or not name or len(name) > 128:
                raise ToolCatalogError("invalid tool name")
            if not isinstance(schema, dict) or schema.get("type") != "object":
                raise ToolCatalogError("invalid tool input schema")
            if name in names:
                raise ToolCatalogError("duplicate tool name")
            names.add(name)
            result.append(dict(tool))
    return result
