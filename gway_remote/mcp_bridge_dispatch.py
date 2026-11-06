"""Fail-closed Watchtower infrastructure dispatcher for the private MCP bridge.

The caller must supply an independently verified principal authorization check.
The signed envelope alone is never proof that a principal holds a scope.
Execution is deliberately not wired until the existing request ownership
and eligibility checks can be preserved end to end.
"""
from __future__ import annotations

from . import node_registry_inventory
from .mcp_bridge_contract import InvalidBridgeRequest


class WatchtowerBridgeDispatch:
    def __init__(self, *, authorize, inventory=None):
        if not callable(authorize):
            raise TypeError("authorization callback required")
        self.authorize = authorize
        self.inventory = inventory or node_registry_inventory

    def __call__(self, envelope):
        principal = envelope["principal"]
        scope = envelope["scope"]
        audience = envelope["audience"]
        operation = envelope["operation"]
        arguments = envelope["arguments"]
        # The verifier must independently bind the authenticated principal,
        # intended node and scope to an active authorization.
        if self.authorize(principal, audience, scope) is not True:
            raise PermissionError("bridge principal not authorized")
        if operation == "inventory.list" and arguments == {}:
            return self.inventory.public_nodes(execution_enabled=False)
        if operation == "inventory.capabilities" and set(arguments) == {"node"}:
            return self.inventory.capabilities(arguments["node"], execution_enabled=False)
        # No implicit command execution, preview, or deploy fallback.
        raise InvalidBridgeRequest("bridge operation not enabled")
