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


def inspect_authorized(arguments: dict) -> dict:
    if type(arguments) is not dict or set(arguments) != {"node", "repository"}:
        raise ValueError("invalid workspace inspection arguments")
    node, repository = arguments["node"], arguments["repository"]
    if not isinstance(node, str) or not isinstance(repository, str):
        raise ValueError("invalid workspace selector")
    # Local provider is pinned to the node identity configured by the operator.
    if node != os.environ.get("GWAY_WORKSPACE_NODE", "") or not node:
        raise PermissionError("workspace node unavailable")
    config = os.environ.get("GWAY_WORKSPACE_INSPECT_CONFIG", "")
    if not config or not os.path.isabs(config):
        raise PermissionError("workspace inspection not configured")
    path = Path(config)
    if path.is_symlink():
        raise PermissionError("workspace configuration must not be a symlink")
    stat = path.stat()
    if stat.st_mode & 0o022:
        raise PermissionError("workspace configuration is writable by group or others")
    if stat.st_size > 65536:
        raise ValueError("workspace configuration too large")
    with path.open("r", encoding="utf-8") as stream:
        roots = json.load(stream)
    if type(roots) is not dict or any(
        not isinstance(key, str) or not isinstance(value, str) or not os.path.isabs(value)
        for key, value in roots.items()
    ):
        raise ValueError("invalid workspace configuration")
    return inspect_workspace(repository, roots, node=node)
