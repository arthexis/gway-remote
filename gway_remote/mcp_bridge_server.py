"""Wire a trusted gateway session to the private Watchtower Unix transport.

This is a per-session factory, not an Internet-facing listener. Only the
gateway may create a binding after verifying OAuth and node authorization.
The caller's signed envelope cannot select another session.
"""
from __future__ import annotations

from .mcp_bridge_session import SessionBridgeDispatch
from .mcp_bridge_transport import AuthenticatedBridge, BridgeUnixServer


def bind_gateway_session(*, key, audience, verifier, session_token,
                         allowed_node, read_principal, execution=None,
                         inventory=None, read_transport=None):
    """Create an authenticated bridge with a single trusted OAuth session.

    Re-check the credential on every request (including after revocation).
    Node selection is fixed at construction, never taken from user input.
    """
    if not isinstance(audience, str) or not audience:
        raise ValueError("audience required")
    if not isinstance(session_token, str) or not session_token:
        raise ValueError("session token required")
    if allowed_node(session_token, audience) is not True:
        raise PermissionError("session not authorized for node")
    if not verifier.verify(session_token, required_scope="gway:read"):
        # Execute-only credentials may exist; verify those explicitly.
        if not verifier.verify(session_token, required_scope="gway:execute"):
            raise PermissionError("invalid gateway session")
    dispatch = SessionBridgeDispatch(
        verifier=verifier, session_token=session_token,
        allowed_node=allowed_node, read_principal=read_principal,
        execution=execution, inventory=inventory,
        read_transport=read_transport)
    return AuthenticatedBridge(key, audience=audience, dispatch=dispatch)


def serve_gateway_session(path, *, key, audience, verifier, session_token,
                          allowed_node, read_principal, execution=None,
                          inventory=None, read_transport=None):
    """Construct a private Unix server; caller owns serve_forever and shutdown."""
    bridge = bind_gateway_session(
        key=key, audience=audience, verifier=verifier,
        session_token=session_token, allowed_node=allowed_node,
        read_principal=read_principal, execution=execution,
        inventory=inventory)
    return BridgeUnixServer(path, bridge)

def serve_managed_sessions(path, *, key, audience, sessions):
    """Serve multiple gateway-owned sessions over one private Unix socket.

    Session registration is deliberately separate: only a trusted gateway
    request handler can call sessions.register with a verified bearer.
    """
    if sessions is None or not callable(getattr(sessions, "dispatch", None)):
        raise TypeError("session manager required")
    bridge = AuthenticatedBridge(key, audience=audience, dispatch=None,
                                 sessions=sessions)
    return BridgeUnixServer(path, bridge)
