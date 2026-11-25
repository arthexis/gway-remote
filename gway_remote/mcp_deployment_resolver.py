"""Resolve deployment eligibility exclusively from node-owned installed providers.

This read-only resolver does not dispatch or grant execute permission.
"""
import re

from .mcp_installed_providers import discover_installed_providers

_APP = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{1,39}$")

# These aliases are code-owned, not supplied by a caller or inventory.
APPLICATION_ALIASES = {"gway-lcd-sound": "lcd_sound", "gway-agent-ops": "agentops"}


def normalize_application(application):
    """Normalize only fixed code-owned aliases before any request is bound."""
    if type(application) is not str or not _IDENTIFIER.fullmatch(application):
        raise ValueError("deployment_invalid_application")
    canonical = APPLICATION_ALIASES.get(application, application)
    if not _APP.fullmatch(canonical):
        raise ValueError("deployment_unknown_application")
    return canonical


def deployment_catalog(*, discover=discover_installed_providers):
    """Return bounded, path-free declaration information from installed providers.

    A declaration is not proof that its runner is currently executable or that
    an application is installed at the declared target revision.
    """
    from .mcp_deployment_contract import validate_deployment

    sources = tuple(discover())
    if len(sources) > 32 or len({source.source_id for source in sources}) != len(sources):
        raise PermissionError("deployment_declaration_invalid")
    if len(set(APPLICATION_ALIASES.values())) != len(APPLICATION_ALIASES):
        raise PermissionError("deployment_declaration_invalid")
    names = {source.source_id for source in sources}
    if any(alias in names or not _IDENTIFIER.fullmatch(alias) or
           not _APP.fullmatch(canonical)
           for alias, canonical in APPLICATION_ALIASES.items()):
        raise PermissionError("deployment_declaration_invalid")
    aliases = {canonical: alias for alias, canonical in APPLICATION_ALIASES.items()}
    result = []
    for source in sorted(sources, key=lambda item: item.source_id):
        revision = None
        if not source.enabled:
            status = "not_enabled"
        elif source.deployment is None:
            status = "no_declaration"
        else:
            try:
                revision = validate_deployment(source.deployment)["revision"]
                status = "declared"
            except (ValueError, TypeError, KeyError):
                status = "declaration_invalid"
        result.append({"application": source.source_id,
                       "alias": aliases.get(source.source_id),
                       "revision": revision, "status": status})
    return result


def resolve_deployment(application, *, discover=discover_installed_providers):
    if type(application) is not str or not _APP.fullmatch(application):
        raise ValueError("invalid deployment application")
    sources = tuple(discover())
    # Validate the whole registry, including alias collisions, before resolving.
    deployment_catalog(discover=lambda: sources)
    matches = [source for source in sources if source.source_id == application]
    if not matches:
        raise PermissionError("deployment_unknown_application")
    if not matches[0].enabled:
        raise PermissionError("deployment_not_enabled")
    if matches[0].deployment is None:
        raise PermissionError("deployment_no_declaration")
    from .mcp_deployment_contract import validate_deployment
    try:
        return validate_deployment(matches[0].deployment)
    except (ValueError, TypeError, KeyError):
        raise PermissionError("deployment_declaration_invalid") from None

DEPLOYMENT_NODE_ERRORS = frozenset({
    "deployment_invalid_application", "deployment_unknown_application",
    "deployment_not_enabled", "deployment_no_declaration",
    "deployment_declaration_invalid", "deployment_declaration_drift",
    "deployment_permission_denied", "deployment_request_not_found",
    "deployment_node_protocol_unavailable",
})

def deployment_error_code(exc):
    # Match only fixed origin messages; never emit exception text or paths.
    if str(exc) in DEPLOYMENT_NODE_ERRORS:
        return str(exc)
    if str(exc) in {"deployment revision changed since preview",
                    "request bound to another deployment revision"}:
        return "deployment_declaration_drift"
    if str(exc) == "deployment request not found":
        return "deployment_request_not_found"
    if str(exc) == "invalid deployment application":
        return "deployment_invalid_application"
    if isinstance(exc, PermissionError):
        return "deployment_permission_denied"
    return "deployment_node_protocol_unavailable"
