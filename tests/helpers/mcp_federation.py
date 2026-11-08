"""Deterministic node-owned MCP catalog fixture; no network or execution."""
from gway_remote.mcp_tool_scope import required_scope


class FederationCatalogFixture:
    def __init__(self, tools, *, source='fixture', node='gway-001', route_names=None):
        self.tools = tools
        self.source = source
        self.node = node
        self.route_names = route_names or {}

    def discover(self, builtins=()):
        catalog = list(builtins) + [dict(tool) for tool in self.tools]
        routes = {}
        for tool in self.tools:
            name = tool['name']
            routes[name] = (self.node, self.source,
                            self.route_names.get(name, name), required_scope(tool))
        return catalog, routes


def fixture_tool(name, *, read=False, destructive=False):
    tool = {'name': name, 'inputSchema': {'type': 'object'}}
    if read or destructive:
        tool['annotations'] = {'readOnlyHint': read}
        if destructive:
            tool['annotations']['destructiveHint'] = True
    return tool
