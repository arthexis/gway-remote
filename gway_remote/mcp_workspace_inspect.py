"""Fail-closed, operator-configured local workspace inspection provider.

The gateway cannot accept filesystem paths from MCP clients. An administrator
must configure an absolute JSON file mapping repositories to local checkout
paths. Missing configuration is never an invitation to execute a shell.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .workspace_inspect import inspect_workspace


class WorkspaceUnavailable(PermissionError):
    """Sanitized, stable read-only inspection failure."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def inspect_authorized(arguments: dict, *, deployment_receipt: dict | None = None) -> dict:
    if type(arguments) is not dict or set(arguments) != {"node", "repository"}:
        raise ValueError("invalid workspace inspection arguments")
    node, repository = arguments["node"], arguments["repository"]
    if not isinstance(node, str) or not isinstance(repository, str):
        raise ValueError("invalid workspace selector")
    # Local provider is pinned to the node identity configured by the operator.
    if node != os.environ.get("GWAY_WORKSPACE_NODE", "") or not node:
        raise WorkspaceUnavailable("node_binding_mismatch")
    config = os.environ.get("GWAY_WORKSPACE_INSPECT_CONFIG", "")
    if not config or not os.path.isabs(config):
        raise WorkspaceUnavailable("workspace_not_configured")
    path = Path(config)
    if path.is_symlink():
        raise WorkspaceUnavailable("workspace_config_invalid")
    stat = path.stat()
    if stat.st_mode & 0o022:
        raise WorkspaceUnavailable("workspace_config_invalid")
    if stat.st_size > 65536:
        raise WorkspaceUnavailable("workspace_config_invalid")
    with path.open("r", encoding="utf-8") as stream:
        roots = json.load(stream)
    if type(roots) is not dict or any(
        not isinstance(key, str) or not isinstance(value, str) or not os.path.isabs(value)
        for key, value in roots.items()
    ):
        raise WorkspaceUnavailable("workspace_config_invalid")
    if repository not in roots:
        raise WorkspaceUnavailable("repository_not_allowlisted")
    # Only trusted server-side callers may supply a verified activation receipt.
    # Never accept receipt data or paths from MCP request arguments.
    return inspect_workspace(repository, roots, node=node,
                             deployment_receipt=deployment_receipt)
