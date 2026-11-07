"""Node-owned MCP provider discovery and invocation.

This module runs on the enrolled node, never on Watchtower. The authenticated
node transport must supply the caller's effective scope; arguments cannot
upgrade authorization. Provider registrations are operator-provisioned.
"""
from .mcp_source_policy import classify_source_catalog
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


def _registration(registrations, provider):
    if type(provider) is not str or not provider:
        raise NodeProviderError("invalid_provider")
    matching = [r for r in registrations if r.source_id == provider and r.enabled]
    if len(matching) != 1:
        raise NodeProviderError("provider_not_registered", provider=provider)
    return matching[0]


def _catalog(registration):
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
                "tools": catalog["read"] + catalog["execute_required"],
            })
        except NodeProviderError as exc:
            providers.append({
                "provider": registration.source_id, "node": node_id,
                "revision": registration.revision, "status": "unavailable",
                "tools": [], "error": exc.as_dict(),
            })
    return {"node": node_id, "providers": providers}


def provider_call(registrations, *, provider, tool, arguments, authorized_scope):
    """Revalidate a declaration and enforce permissions on the owning node."""
    if authorized_scope not in ("read", "execute"):
        raise NodeProviderError("permission_denied", provider=provider)
    if type(tool) is not str or not tool or type(arguments) is not dict:
        raise NodeProviderError("invalid_arguments", provider=provider)
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
        return call_source_tool(registration, tool, arguments, declaration,
                                authorized_scope=authorized_scope)
    except SourceProtocolError as exc:
        raise NodeProviderError(exc.code, provider=provider, stage=exc.stage,
                                retryable=exc.retryable) from exc
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        raise NodeProviderError("provider_unavailable", provider=provider,
                                stage="execution", retryable=True) from exc

def dispatch_node_provider_request(registrations, request, *, node_id, trusted_scope):
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
        return provider_call(registrations, provider=request["provider"],
                             tool=request["tool"], arguments=request["arguments"],
                             authorized_scope=trusted_scope)
    raise NodeProviderError("unknown_operation")
