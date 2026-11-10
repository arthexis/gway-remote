"""Read-only workspace inspection through already installed node-owned records.

No MCP caller-supplied paths, hostname environment variables, additional
credentials, workspace allowlist or filesystem crawl. Unregistered/inaccessible
checkouts return explicit unknown evidence.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import subprocess
from datetime import datetime, timezone

from .mcp_installed_providers import discover_installed_providers
from .mcp_deployment_contract import validate_deployment
from .workspace_inspect import SCHEMA, inspect_workspace

REGISTRY = Path("/etc/gway-mcp-providers")
_REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_ORIGIN = re.compile(
    r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"([A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*?)(?:\.git)?/?\Z"
)


class WorkspaceUnavailable(PermissionError):
    """Sanitized, stable read-only inspection failure."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _registered_file(path, *, uid):
    """Read only exact root/operator-provisioned policy files, never symlinks."""
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid
            or info.st_mode & 0o022 or info.st_size > 8192):
        raise WorkspaceUnavailable("workspace_registry_invalid")
    return path.read_text(encoding="utf-8")


def _agentops_checkout(repository, *, directory, uid):
    """Existing AgentOps registry names repos and owns its workspace root."""
    if directory.is_symlink():
        raise WorkspaceUnavailable("workspace_registry_invalid")
    info = directory.stat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid
            or info.st_mode & 0o022):
        raise WorkspaceUnavailable("workspace_registry_invalid")
    repo_policy = directory / "agentops.repositories"
    runtime_policy = directory / "agentops.runtime.json"
    if not repo_policy.exists() and not repo_policy.is_symlink():
        return None
    approved = _registered_file(repo_policy, uid=uid).strip().split(",")
    if not approved or any(not _REPOSITORY.fullmatch(item) for item in approved):
        raise WorkspaceUnavailable("workspace_registry_invalid")
    if repository not in approved:
        return None
    runtime = json.loads(_registered_file(runtime_policy, uid=uid))
    if type(runtime) is not dict or type(runtime.get("workspace")) is not str:
        raise WorkspaceUnavailable("workspace_registry_invalid")
    base = Path(runtime["workspace"])
    if not base.is_absolute() or ".." in base.parts:
        raise WorkspaceUnavailable("workspace_registry_invalid")
    # Repository is exactly two validated components. Never list other workspaces.
    return base.joinpath(*repository.split("/"))


def _safe_checkout(path):
    """Reject path traversal, symlinks and writable checkout roots."""
    if not path.is_absolute() or ".." in path.parts:
        return False
    try:
        for part in (path, *path.parents):
            if part.is_symlink():
                return False
        info = path.stat()
        dotgit = path / ".git"
        git_info = dotgit.lstat()
        return (stat.S_ISDIR(info.st_mode) and not info.st_mode & 0o022
                and stat.S_ISDIR(git_info.st_mode) and not dotgit.is_symlink())
    except OSError:
        return False


def _git_origin(path, repository):
    """Check only local Git metadata; never contact remotes or invoke a shell."""
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "-c", "core.fsmonitor=false",
             "config", "--local", "--get", "remote.origin.url"],
            check=False, capture_output=True, text=True, timeout=1,
            env={"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1",
                 "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "0",
                 "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode or len(result.stdout) > 512:
        return False
    match = _ORIGIN.fullmatch(result.stdout.strip())
    return match is not None and match.group(1).lower() == repository.lower()


def _unknown(repository, node, reason):
    """Keep the v1 response shape without inventing checkout or installed SHA."""
    missing = {"state": "unknown", "reason": reason, "value": None}
    return {
        "schema": SCHEMA, "checked_at": datetime.now(timezone.utc).isoformat(),
        "repository": repository, "node": node,
        "git": {"head": dict(missing), "branch": dict(missing),
                "clean_tracked": dict(missing)},
        "ci": {"state": "unknown", "reason": "GitHub evidence not supplied"},
        "deployment": {"state": "unknown", "reason": "deployment evidence not supplied"},
    }


def inspect_authorized(arguments: dict, *, trusted_node: str,
                       deployment_receipt: dict | None = None,
                       discover=discover_installed_providers,
                       registry=REGISTRY, trusted_uid=0) -> dict:
    if type(arguments) is not dict or set(arguments) != {"node", "repository"}:
        raise ValueError("invalid workspace inspection arguments")
    node, repository = arguments["node"], arguments["repository"]
    # The trusted node identity is supplied by the forced protocol, not MCP.
    if (type(trusted_node) is not str or not trusted_node
            or node != trusted_node):
        raise WorkspaceUnavailable("node_binding_mismatch")
    if type(repository) is not str or not _REPOSITORY.fullmatch(repository):
        raise ValueError("invalid repository")

    try:
        candidates = []
        for provider in discover():
            if not provider.enabled or provider.deployment is None:
                continue
            checkout = validate_deployment(provider.deployment)["checkout"]
            candidates.append(Path(checkout))
        candidate = _agentops_checkout(repository, directory=Path(registry),
                                       uid=trusted_uid)
        if candidate is not None:
            candidates.append(candidate)
        # Only paths supplied by already installed records are ever consulted.
        checked = set()
        matches = []
        for path in candidates:
            if path in checked:
                continue
            checked.add(path)
            if _safe_checkout(path) and _git_origin(path, repository):
                matches.append(path)
        if len(matches) != 1:
            return _unknown(repository, node, "repository_not_registered"
                            if not matches else "ambiguous_registered_checkout")
        return inspect_workspace(repository, {repository: str(matches[0])},
                                 node=node, deployment_receipt=deployment_receipt)
    except WorkspaceUnavailable as exc:
        return _unknown(repository, node, exc.code)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return _unknown(repository, node, "workspace_registry_unavailable")
