"""Opt-in owner-bound admission; no credential or caller identity in tool args."""
import re

# Receiver and sender must agree on this operator-reviewed opt-in.
OWNER_BOUND_PROVIDERS = frozenset({"aeon_score"})
_RESERVED = frozenset({"principal", "principal_id", "verified_principal", "auth_context"})

def owner_bound(provider):
    return type(provider) is str and provider in OWNER_BOUND_PROVIDERS

def verify_admission(verifier, credential, scope):
    """Use the authenticated HTTP credential, never the MCP payload."""
    if scope not in ("read", "execute"):
        raise PermissionError("invalid_provider_scope")
    principal = verifier.federated_principal(credential, scope=scope)
    return validate_principal(principal)

def validate_principal(principal):
    if type(principal) is not str or not re.fullmatch(r"[0-9a-f]{24}", principal):
        raise PermissionError("verified_provider_principal_required")
    return principal

def validate_owner_arguments(arguments):
    if type(arguments) is not dict or _RESERVED.intersection(arguments):
        raise PermissionError("reserved_provider_identity_argument")
