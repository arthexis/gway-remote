"""Private MCP tool contract for Agent Ops access.

This is a transport-independent core. It MUST NOT be exposed over public
HTTP without an authenticated MCP transport and operator authorization.
"""
from .mcp_catalog import compose_catalog
from .mcp_source_registry import compose_source_catalog
from .mcp_source_stdio import call_source_tool, list_source_tools
from .mcp_source_policy import classify_source_catalog
from .mcp_tool_scope import required_scope

# GitHub repository tools belong to the federated gway-repo provider.
# GWay Remote retains only node/provider discovery and routing here.
TOOLS = (
    {"name": "mcp_source_status", "description": "Diagnose registered MCP source discovery without revealing secrets or source configuration.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "annotations": {"readOnlyHint": True}},
)

_HANDLERS = {
    "mcp_source_status": lambda arguments: source_status(),
}


_SOURCE_REGISTRATIONS = ()
_SOURCE_APPROVED = {}


def configure_sources(registrations, approved_catalogs):
    """Install operator-approved, release-pinned source catalogs at startup.

    The deployment controller must verify release identity and permissions.
    This is opt-in; an empty registry preserves built-in non-AgentOps tools.
    """
    global _SOURCE_REGISTRATIONS, _SOURCE_APPROVED
    registrations = tuple(registrations)
    approved_catalogs = {key: tuple(value) for key, value in approved_catalogs.items()}
    compose_source_catalog(TOOLS, registrations, approved_catalogs)
    _SOURCE_REGISTRATIONS = registrations
    _SOURCE_APPROVED = approved_catalogs


def _live_source_catalogs():
    """Discover current read-only tools from each already registered source.

    Source registration (not tool enumeration) is the authorization boundary.
    A failing source contributes no tools, without hiding built-in operations.
    """
    catalogs = {}
    for registration in _SOURCE_REGISTRATIONS:
        if not registration.enabled:
            continue
        try:
            classified = classify_source_catalog(registration, list_source_tools(registration))
            catalogs[registration.source_id] = classified["read"] + classified["execute_required"]
        except (OSError, ValueError, RuntimeError, TimeoutError):
            catalogs[registration.source_id] = []
    return catalogs


def source_status():
    """Safe source-level health summary; never disclose argv, paths or tokens."""
    sources = []
    for registration in _SOURCE_REGISTRATIONS:
        if not registration.enabled:
            sources.append({"source": registration.source_id, "enabled": False, "status": "disabled", "tools": []})
            continue
        try:
            catalog = classify_source_catalog(registration, list_source_tools(registration))
            names = sorted(registration.source_id + "__" + t["name"] for t in catalog["read"])
            sources.append({"source": registration.source_id, "enabled": True,
                            "status": "available", "tools": names,
                            "withheld_execute_count": len(catalog["execute_required"])})
        except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
            sources.append({"source": registration.source_id, "enabled": True,
                            "status": "unavailable", "error_type": type(exc).__name__, "tools": []})
    return {"sources": sources, "registered_count": len(_SOURCE_REGISTRATIONS)}


def list_tools():
    """Return built-ins and freshly discovered tools from registered sources."""
    return compose_source_catalog(TOOLS, _SOURCE_REGISTRATIONS, _live_source_catalogs())


def call_tool(name, arguments, *, authorized_scope="read"):
    """Dispatch a trusted tool under the explicitly authorized caller scope."""
    if authorized_scope not in ("read", "execute"):
        raise ValueError("invalid_scope")
    if type(name) is not str:
        raise ValueError("mcp_tool_not_allowed")
    if name not in _HANDLERS:
        for registration in _SOURCE_REGISTRATIONS:
            prefix = registration.source_id + "__"
            if registration.enabled and name.startswith(prefix):
                short_name = name[len(prefix):]
                approved = _live_source_catalogs().get(registration.source_id, ())
                if any(tool.get("name") == short_name for tool in approved):
                    declared = next(tool for tool in approved if tool["name"] == short_name)
                    if required_scope(declared) == "execute" and authorized_scope != "execute":
                        raise ValueError("mcp_execute_scope_required")
                    return call_source_tool(registration, short_name, arguments, declared,
                                            authorized_scope=authorized_scope)
        raise ValueError("mcp_tool_not_allowed")
    if type(arguments) is not dict:
        raise ValueError("invalid_arguments")
    declaration = next(tool for tool in TOOLS if tool["name"] == name)
    if required_scope(declaration) == "execute" and authorized_scope != "execute":
        raise ValueError("mcp_execute_scope_required")
    schema = TOOLS[tuple(_HANDLERS).index(name)]["inputSchema"]
    required = set(schema.get("required", ()))
    if not required <= set(arguments) or set(arguments) - set(schema["properties"]):
        raise ValueError("invalid_arguments")
    return _HANDLERS[name](arguments)
