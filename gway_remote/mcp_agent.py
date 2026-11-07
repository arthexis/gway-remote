"""Private MCP tool contract for Agent Ops access.

This is a transport-independent core. It MUST NOT be exposed over public
HTTP without an authenticated MCP transport and operator authorization.
"""
from . import agent_ops_adapter, github_workflows_mcp
from .mcp_catalog import compose_catalog
from .mcp_source_registry import compose_source_catalog
from .mcp_source_stdio import call_source_tool, list_source_tools
from .mcp_source_policy import classify_source_catalog
from .mcp_tool_scope import required_scope

TOOLS = (
    {"name": "agent_list_issues", "description": "List trusted issues and their eligibility; never dispatch.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "annotations": {"readOnlyHint": True}},
    {"name": "agent_status", "description": "Inspect Agent Ops admission and worker status.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "annotations": {"readOnlyHint": True}},
    {"name": "agent_preview", "description": "Preview one trusted issue; does not execute it.",
     "inputSchema": {"type": "object", "properties": {"ref": {"type": "string"}},
                     "required": ["ref"], "additionalProperties": False},
     "annotations": {"readOnlyHint": True}},
    {"name": "agent_submit", "description": "Submit one trusted issue with a caller-frozen UTC identity; requires gway:execute at the gateway.",
     "inputSchema": {"type": "object", "properties": {
         "ref": {"type": "string"}, "at": {"type": "string"}},
         "required": ["ref", "at"], "additionalProperties": False}},
    {"name": "agent_observe", "description": "Observe a previously submitted issue by frozen UTC identity.",
     "inputSchema": {"type": "object", "properties": {
         "ref": {"type": "string"}, "at": {"type": "string"}},
         "required": ["ref", "at"], "additionalProperties": False},
     "annotations": {"readOnlyHint": True}},
    {"name": "github_workflow_runs", "description": "Read recent GitHub Actions runs across allowed repositories.",
     "inputSchema": {"type": "object", "properties": {"repository": {"type": "string"}, "branch": {"type": "string"}, "status": {"type": "string"}, "event": {"type": "string"}, "limit": {"type": "integer"}}, "additionalProperties": False}, "annotations": {"readOnlyHint": True}},
    {"name": "github_workflow_status", "description": "Read one workflow run, jobs and steps.",
     "inputSchema": {"type": "object", "properties": {"repository": {"type": "string"}, "run_id": {"type": "integer"}}, "required": ["repository", "run_id"], "additionalProperties": False}, "annotations": {"readOnlyHint": True}},
    {"name": "mcp_source_status", "description": "Diagnose registered MCP source discovery without revealing secrets or source configuration.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "annotations": {"readOnlyHint": True}},
    {"name": "github_workflow_errors", "description": "Read failed job/step metadata; unsafe build logs are withheld.",
     "inputSchema": {"type": "object", "properties": {"repository": {"type": "string"}, "run_id": {"type": "integer"}, "job_id": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["repository", "run_id"], "additionalProperties": False}, "annotations": {"readOnlyHint": True}},
)

_HANDLERS = {
    "agent_list_issues": agent_ops_adapter.issues,
    "agent_status": agent_ops_adapter.status,
    "agent_preview": agent_ops_adapter.preview_issue,
    "agent_observe": agent_ops_adapter.observe_issue,
    "agent_submit": agent_ops_adapter.send_issue,
    "github_workflow_runs": github_workflows_mcp.runs,
    "github_workflow_status": github_workflows_mcp.status,
    "mcp_source_status": lambda arguments: source_status(),
    "github_workflow_errors": github_workflows_mcp.errors,
}


_SOURCE_REGISTRATIONS = ()
_SOURCE_APPROVED = {}


def configure_sources(registrations, approved_catalogs):
    """Install operator-approved, release-pinned source catalogs at startup.

    The deployment controller must verify release identity and permissions.
    This is opt-in; an empty registry preserves legacy behavior.
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
