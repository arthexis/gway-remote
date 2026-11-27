"""Node-owned MCP provider discovery and invocation.

This module runs on the enrolled node, never on Watchtower. The authenticated
node transport must supply the caller's effective scope; arguments cannot
upgrade authorization. Provider registrations are operator-provisioned.
"""
from .mcp_source_policy import classify_source_catalog
from dataclasses import replace
import os
import pwd
from .mcp_source_stdio import SourceProtocolError, call_source_tool, list_source_tools
from .mcp_tool_scope import required_scope


class NodeProviderError(RuntimeError):
    def __init__(self, code, *, provider=None, stage="dispatch", retryable=False):
        self.code = code
        self.provider = provider
        self.stage = stage
        self.retryable = retryable
        super().__init__(code)

    def as_dict(self):
        return {"code": self.code, "provider": self.provider,
                "stage": self.stage, "retryable": self.retryable}


def _node_registration(registration):
    """Run every provider as the node service account, never a provider account.

    The legacy run_as field is retained in the registry wire format for
    compatibility, but it cannot select a different OS identity here.
    """
    if os.geteuid() == 0:
        raise NodeProviderError("root_execution_forbidden",
                                provider=registration.source_id)
    return replace(registration, run_as=pwd.getpwuid(os.geteuid()).pw_name)


def _registration(registrations, provider):
    if type(provider) is not str or not provider:
        raise NodeProviderError("invalid_provider")
    matching = [r for r in registrations if r.source_id == provider and r.enabled]
    if len(matching) != 1:
        raise NodeProviderError("provider_not_registered", provider=provider)
    return matching[0]


def _catalog(registration):
    registration = _node_registration(registration)
    try:
        return classify_source_catalog(registration, list_source_tools(registration))
    except SourceProtocolError as exc:
        raise NodeProviderError(exc.code, provider=registration.source_id,
                                stage=exc.stage, retryable=exc.retryable) from exc
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        raise NodeProviderError("provider_unavailable", provider=registration.source_id,
                                stage="discovery", retryable=True) from exc


def provider_list(registrations, *, node_id):
    """Discover all locally registered providers, isolating individual failures."""
    if type(node_id) is not str or not node_id:
        raise NodeProviderError("invalid_node")
    providers = []
    for registration in registrations:
        if not registration.enabled:
            continue
        try:
            catalog = _catalog(registration)
            providers.append({
                "provider": registration.source_id, "node": node_id,
                "revision": registration.revision, "status": "available",
                # Capability is emitted only by a runtime that already supports
                # provider_read. Old Watchtower parsers ignore extra provider
                # fields, allowing receiver-first rollout without downtime.
                "supports_provider_read": True,
                "tools": catalog["read"] + catalog["execute_required"],
            })
        except NodeProviderError as exc:
            providers.append({
                "provider": registration.source_id, "node": node_id,
                "revision": registration.revision, "status": "unavailable",
                "tools": [], "error": exc.as_dict(),
            })
    return {"node": node_id, "providers": providers}


def provider_call(registrations, *, provider, tool, arguments, authorized_scope,
                  invocation_id=None, verified_principal=None):
    """Revalidate a declaration and enforce permissions on the owning node."""
    if authorized_scope not in ("read", "execute"):
        raise NodeProviderError("permission_denied", provider=provider)
    if type(tool) is not str or not tool or type(arguments) is not dict:
        raise NodeProviderError("invalid_arguments", provider=provider)
    from .mcp_principal_admission import owner_bound, validate_principal, validate_owner_arguments
    if owner_bound(provider):
        if verified_principal is None:
            raise NodeProviderError("principal_bound_transport_required", provider=provider)
        validate_principal(verified_principal)
        validate_owner_arguments(arguments)
    elif verified_principal is not None:
        raise NodeProviderError("unexpected_provider_principal", provider=provider)
    registration = _registration(registrations, provider)
    catalog = _catalog(registration)
    matching = [t for t in catalog["read"] + catalog["execute_required"]
                if t["name"] == tool]
    if len(matching) != 1:
        raise NodeProviderError("tool_not_found", provider=provider)
    declaration = matching[0]
    if required_scope(declaration) == "execute" and authorized_scope != "execute":
        raise NodeProviderError("permission_denied", provider=provider)
    try:
        # Issue arthexis/odoo-gelectriic#62: one reviewed batch performs up to
        # four independent Odoo readbacks. Extend ONLY this declared tool's
        # stdio budget, leaving 5s for the existing 30s gateway deadline.
        # Authorization and declaration revalidation still run unchanged.
        options = {"authorized_scope": authorized_scope}
        if verified_principal is not None:
            options["verified_principal"] = verified_principal
        if registration.source_id == "android" and invocation_id is not None:
            options["invocation_id"] = invocation_id
        if registration.source_id == "odoo" and tool == "customer_vehicle_batch_apply":
            options["timeout"] = 25
        # CRM guarded writer has a 25s subprocess budget.
        if registration.source_id == "odoo" and tool in (
                "crm_opportunity_create", "crm_opportunity_update",
                "crm_opportunity_stage_move"):
            options["timeout"] = 28
        if registration.source_id == "android" and tool == "scenario_run":
            from .android_execution_contract import STDIO_SECONDS
            options["timeout"] = STDIO_SECONDS
        return call_source_tool(_node_registration(registration), tool, arguments, declaration,
                                **options)
    except SourceProtocolError as exc:
        if (provider == "android" and tool == "scenario_run" and authorized_scope == "execute"
                and exc.code not in ("permission_denied", "tool_declaration_changed",
                                     "invalid invocation id", "invalid tool timeout")):
            from .android_execution_contract import uncertain_result
            code = "provider_timeout" if exc.code == "provider_timeout" else "provider_execution_uncertain"
            return uncertain_result(arguments, invocation_id, code)
        raise NodeProviderError(exc.code, provider=provider, stage=exc.stage,
                                retryable=exc.retryable) from exc
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        if provider == "android" and tool == "scenario_run" and authorized_scope == "execute":
            from .android_execution_contract import uncertain_result
            return uncertain_result(arguments, invocation_id, "provider_execution_uncertain")
        raise NodeProviderError("provider_unavailable", provider=provider,
                                stage="execution", retryable=True) from exc

def dispatch_node_provider_request(registrations, request, *, node_id, trusted_scope,
                                   invocation_id=None):
    """RPC entrypoint for an authenticated node transport.

    The transport MUST derive trusted_scope from its authenticated peer and
    MUST NOT accept it from request payload. Never shell out from Watchtower.
    """
    if type(request) is not dict or set(request) - {"operation", "provider", "tool", "arguments"}:
        raise NodeProviderError("invalid_request")
    operation = request.get("operation")
    if operation == "provider_list":
        if set(request) != {"operation"}:
            raise NodeProviderError("invalid_request")
        return provider_list(registrations, node_id=node_id)
    if operation == "provider_call":
        if set(request) != {"operation", "provider", "tool", "arguments"}:
            raise NodeProviderError("invalid_request")
        options = {"authorized_scope": trusted_scope}
        if invocation_id is not None and request["provider"] == "android":
            options["invocation_id"] = invocation_id
        return provider_call(registrations, provider=request["provider"],
                             tool=request["tool"], arguments=request["arguments"], **options)
    raise NodeProviderError("unknown_operation")
