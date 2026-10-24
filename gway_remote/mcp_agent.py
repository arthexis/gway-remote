"""Private MCP tool contract for read-only Agent Ops access.

This is a transport-independent core. It MUST NOT be exposed over public
HTTP without an authenticated MCP transport and operator authorization.
"""
from . import agent_ops_adapter, github_workflows_mcp

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
    "github_workflow_runs": github_workflows_mcp.runs,
    "github_workflow_status": github_workflows_mcp.status,
    "github_workflow_errors": github_workflows_mcp.errors,
}


def list_tools():
    """Return an independent tool inventory with no mutating operations."""
    return [dict(tool) for tool in TOOLS]


def call_tool(name, arguments):
    """Execute a fixed read-only operation through the existing trusted adapter."""
    if type(name) is not str or name not in _HANDLERS:
        raise ValueError("mcp_tool_not_allowed")
    if type(arguments) is not dict:
        raise ValueError("invalid_arguments")
    schema = TOOLS[tuple(_HANDLERS).index(name)]["inputSchema"]
    required = set(schema.get("required", ()))
    if not required <= set(arguments) or set(arguments) - set(schema["properties"]):
        raise ValueError("invalid_arguments")
    return _HANDLERS[name](arguments)
