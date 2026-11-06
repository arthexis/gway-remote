"""Watchtower-side authorization adapter for the private bridge.

An envelope's principal/scope are untrusted claims even if its transport
signature is valid. Bind them to a gateway-verified bearer credential on every
call. Credential resolution is injected by the gateway and MUST NOT use
client-provided envelope fields as a token or as proof of authorization.
"""
from __future__ import annotations

from .mcp_bearer import BearerVerifier
from .mcp_bridge_dispatch import WatchtowerBridgeDispatch
from . import node_registry_inventory


class BridgeAuthorization:
    def __init__(self, *, verifier, credential_for_principal, allowed_node):
        if not callable(credential_for_principal) or not callable(allowed_node):
            raise TypeError("trusted credential and node policy callbacks required")
        self.verifier = verifier
        self.credential_for_principal = credential_for_principal
        self.allowed_node = allowed_node

    def __call__(self, principal, audience, scope):
        if scope not in ("gway:read", "gway:execute"):
            return False
        try:
            if self.allowed_node(principal, audience) is not True:
                return False
            # Only a trusted gateway-maintained session may supply this token.
            credential = self.credential_for_principal(principal)
            if not isinstance(credential, str):
                return False
            if not self.verifier.verify(credential, required_scope=scope):
                return False
            if scope == "gway:execute":
                # Bind execution to the stable, revocable OAuth parent identity.
                return self.verifier.execution_principal(credential) == principal
            return True
        except (PermissionError, ValueError, OSError, KeyError):
            return False


def make_authorized_dispatch(*, registry_path, credential_for_principal, allowed_node,
                             inventory=None):
    verifier = BearerVerifier(registry_path)
    authorization = BridgeAuthorization(
        verifier=verifier, credential_for_principal=credential_for_principal,
        allowed_node=allowed_node)
    return WatchtowerBridgeDispatch(
        authorize=authorization, inventory=inventory or node_registry_inventory)
