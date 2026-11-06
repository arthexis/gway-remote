"""Private MCP tool contract for Agent Ops access.

This is a transport-independent core. It MUST NOT be exposed over public
HTTP without an authenticated MCP transport and operator authorization.
"""
from . import agent_ops_adapter, github_workflows_mcp
from .mcp_catalog import compose_catalog
from .mcp_source_registry import compose_source_catalog
from .mcp_source_stdio import call_source_tool

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


def list_tools():
    """Return the fixed, audited tool inventory."""
    return compose_source_catalog(TOOLS, _SOURCE_REGISTRATIONS, _SOURCE_APPROVED)


def call_tool(name, arguments):
    """Execute a fixed operation through the existing trusted adapter."""
    if type(name) is not str:
        raise ValueError("mcp_tool_not_allowed")
    if name not in _HANDLERS:
        for registration in _SOURCE_REGISTRATIONS:
            prefix = registration.source_id + "__"
            if registration.enabled and name.startswith(prefix):
                short_name = name[len(prefix):]
                approved = _SOURCE_APPROVED.get(registration.source_id, ())
                if any(tool.get("name") == short_name for tool in approved):
                    return call_source_tool(registration, short_name, arguments, approved)
        raise ValueError("mcp_tool_not_allowed")
    if type(arguments) is not dict:
        raise ValueError("invalid_arguments")
    schema = TOOLS[tuple(_HANDLERS).index(name)]["inputSchema"]
    required = set(schema.get("required", ()))
    if not required <= set(arguments) or set(arguments) - set(schema["properties"]):
        raise ValueError("invalid_arguments")
    return _HANDLERS[name](arguments)
