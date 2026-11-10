"""Session-bound Watchtower bridge dispatcher.

A bridge HMAC authenticates the transport, not the OAuth user. Construct this
dispatcher only with a bearer token obtained from the trusted gateway session.
Never resolve credentials from an envelope-provided principal.
"""
from __future__ import annotations

from .mcp_bridge_contract import InvalidBridgeRequest
from .mcp_bearer import BearerVerifier
from . import node_registry_inventory
import secrets


class SessionBridgeDispatch:
    def __init__(self, *, verifier, session_token, allowed_node, read_principal, execution=None,
                 inventory=None):
        if not isinstance(session_token, str) or not session_token:
            raise ValueError("trusted session token required")
        if not callable(allowed_node) or not callable(read_principal):
            raise TypeError("node authorization callback required")
        self.verifier = verifier
        self.session_token = session_token
        self.allowed_node = allowed_node
        self.read_principal = read_principal
        self.execution = execution
        self.inventory = inventory or node_registry_inventory

    def __call__(self, envelope):
        token = self.session_token
        audience = envelope["audience"]
        scope = envelope["scope"]
        operation = envelope["operation"]
        args = envelope["arguments"]
        # A session pinned to one node cannot dispatch to another node through
        # operation arguments, even when the envelope audience is valid.
        if "node" in args and args["node"] != audience:
            raise PermissionError("operation node differs from session audience")
        if not self.verifier.verify(token, required_scope=scope):
            raise PermissionError("expired or revoked session")
        if self.allowed_node(token, audience) is not True:
            raise PermissionError("node not authorized")
        # Execute requests are bound to the stable OAuth parent identity.
        if scope == "gway:execute":
            principal = self.verifier.execution_principal(token)
            if envelope["principal"] != principal:
                raise PermissionError("principal mismatch")
        else:
            # Read sessions are explicitly bound by the trusted gateway
            # callback, not by any claim in the request body.
            if envelope["principal"] != self.read_principal(token):
                raise PermissionError("principal mismatch")
        if operation == "file.read":
            if (scope != "gway:read" or self.execution is None
                    or set(args) != {"node", "filename", "offset"}):
                raise PermissionError("file read unavailable")
            request_id = secrets.token_hex(16)
            response = self.execution.relay.transport.invoke({
                "operation": "file_read", "node": audience,
                "request_id": request_id,
                "filename": args["filename"], "offset": args["offset"]})
            if (type(response) is not dict or response.get("node") != audience
                    or response.get("request_id") != request_id
                    or type(response.get("result")) is not dict):
                raise PermissionError("uncorrelated file response")
            return response["result"]
        if operation == "workspace.inspect" and set(args) == {"node", "repository"}:
            # Reuse the already authenticated, pinned node transport, exactly
            # as file.read and federated provider reads do. Scope is enforced
            # by the OAuth bridge, never by switching SSH identities.
            if scope != "gway:read" or self.execution is None:
                raise PermissionError("workspace inspection unavailable")
            rid = secrets.token_hex(16)
            response = self.execution.relay.transport.invoke({
                "operation": "workspace_inspect", "node": audience,
                "request_id": rid, "repository": args["repository"]})
            if (type(response) is not dict or response.get("node") != audience
                    or response.get("request_id") != rid
                    or type(response.get("result")) is not dict
                    or response["result"].get("node") != audience
                    or response["result"].get("repository") != args["repository"]):
                raise PermissionError("uncorrelated workspace inspection")
            return response["result"]
        if operation == "inventory.list" and args == {}:
            return self.inventory.public_nodes(execution_enabled=self.execution is not None)
        if operation == "inventory.capabilities" and set(args) == {"node"}:
            return self.inventory.capabilities(args["node"],
                execution_enabled=self.execution is not None)
        if operation == "execution.preview" and set(args) == {"node", "command"}:
            from .mcp_bearer_gateway import local_node_result
            return local_node_result("node_exec_preview", args, execution=self.execution)
        if operation == "deployment.preview" and set(args) in (
                {"node", "application"}, {"node", "application", "revision"}):
            if self.execution is None:
                raise PermissionError("execution unavailable")
            from .mcp_bridge_transport import BridgeReadUnavailable
            try:
                return self.execution.deployment_preview(**args)
            except PermissionError as exc:
                code = str(exc)
                if code in BridgeReadUnavailable.CODES and code.startswith("deployment_"):
                    raise BridgeReadUnavailable(code) from None
                raise
        if scope != "gway:execute" or self.execution is None:
            raise PermissionError("execution unavailable")
        if operation == "execution.start" and set(args) in (
                {"node", "command", "request_id"},
                {"node", "command", "request_id", "wait_seconds"}):
            return self.execution.exec(principal=principal, **args)
        if operation == "execution.result" and set(args) in (
                {"request_id"}, {"request_id", "cursor"}):
            return self.execution.result(principal=principal, **args)
        if operation == "execution.cancel" and set(args) == {"request_id"}:
            return self.execution.cancel(principal=principal, **args)
        if operation in ("deployment.start", "deployment.status") and set(args) in (
                {"node", "application", "request_id"},
                {"node", "application", "request_id", "revision"}):
            return self.execution.deployment(
                principal=principal, status=operation == "deployment.status", **args)
        raise InvalidBridgeRequest("unsupported operation or arguments")

