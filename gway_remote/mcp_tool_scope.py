"""Single source of truth for MCP tool access classification.

Registered providers declare tool intent using standard MCP annotations.
Missing or ambiguous annotations are execute-required, never read-only.
The authenticated gateway must enforce the returned scope before dispatch.
"""


def required_scope(tool):
    """Return 'read' only for an explicitly safe MCP tool declaration."""
    if type(tool) is not dict:
        raise ValueError("invalid MCP tool declaration")
    annotations = tool.get("annotations")
    if (type(annotations) is dict
            and annotations.get("readOnlyHint") is True
            and annotations.get("destructiveHint") is not True):
        return "read"
    return "execute"
