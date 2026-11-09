"""Explicit Watchtower policy for manual MCP deployments.

This is a pure validation contract. It does not grant shell execution or
automatically schedule deployment on customer nodes.
"""
from __future__ import annotations

import re

from .wireguard_satellite import DEVICE_RE

REPOSITORY_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*/[a-zA-Z0-9][a-zA-Z0-9_.-]*\Z")
REVISION_RE = re.compile(r"(?:[0-9a-f]{40}|main)\Z")

# First pilot only. The broker must enforce this independently of node_exec.
MANUAL_DEPLOY_TARGETS = {
    "gway-001": frozenset({"arthexis/ocpp-reports", "arthexis/odoo-gelectriic"}),
    "ocpp-abb-1": frozenset({"arthexis/ocpp-reports"}),
}


def validate_deployment(repository: str, node: str, revision: str = "main") -> dict:
    """Validate the requested operation before any remote dispatch.

    A later broker must also verify active enrollment, attestation, reachability,
    immutable SHA resolution and its root-owned deployment authorization.
    """
    if type(node) is not str or not DEVICE_RE.fullmatch(node):
        raise ValueError("invalid deployment node")
    if type(repository) is not str or not REPOSITORY_RE.fullmatch(repository):
        raise ValueError("invalid deployment repository")
    if repository not in MANUAL_DEPLOY_TARGETS.get(node, ()):
        raise PermissionError("repository is not approved for deployment on node")
    if type(revision) is not str or not REVISION_RE.fullmatch(revision):
        raise ValueError("deployment revision must be main or a full commit SHA")
    return {"node": node, "repository": repository, "revision": revision}
