"""Provider RPC adapter over the existing pinned Watchtower-to-node SSH channel.

No additional key, listener, or shell execution. OAuth scope is checked by
Watchtower before the request enters this operator-pinned channel.
"""
import secrets
import subprocess
import time

from .watchtower_exec_transport import pinned_transport


class ProviderTransport:
    def __init__(self, execution_transport):
        self.execution_transport = execution_transport

    def invoke_principal(self, node, request, *, trusted_scope, verified_principal):
        from .mcp_owner_bound_wire import make_payload
        payload = make_payload(node, request, trusted_scope, verified_principal,
                               secrets.token_hex(16))
        response = pinned_transport(self.execution_transport, node).invoke(payload)
        if (type(response) is not dict or response.get("node") != node
                or response.get("request_id") != payload["request_id"]
                or "result" not in response):
            raise ValueError("uncorrelated_owner_response")
        return response["result"]

    def invoke(self, node, request, *, trusted_scope):
        if trusted_scope not in ("read", "execute"):
            raise PermissionError("invalid provider scope")
        if type(request) is not dict or request.get("operation") not in ("provider_list", "provider_call", "provider_read"):
            raise ValueError("invalid provider operation")
        operation = request["operation"]
        if set(request) != ({"operation"} if operation == "provider_list"
                               else {"operation", "provider", "tool", "arguments"}):
            raise ValueError("invalid provider request")
        if operation in ("provider_call", "provider_read") and type(request["arguments"]) is not dict:
            raise ValueError("invalid provider arguments")
        if operation == "provider_read" and trusted_scope != "read":
            raise PermissionError("read operation requires read-only admission")
        if operation == "provider_call" and trusted_scope != "execute":
            raise PermissionError("provider_call requires execute admission")
        payload = {"operation": operation, "node": node,
                   "request_id": secrets.token_hex(16)}
        if operation in ("provider_call", "provider_read"):
            payload.update({key: request[key] for key in ("provider", "tool", "arguments")})
        transport = pinned_transport(self.execution_transport, node)
        started = time.monotonic()
        scenario = (operation == "provider_call" and request.get("provider") == "android"
                    and request.get("tool") == "scenario_run")
        try:
            response = transport.invoke(payload)
            if type(response) is not dict or "result" not in response:
                raise ValueError("invalid provider response")
            if scenario and (response.get("request_id") != payload["request_id"]
                             or response.get("node") != node):
                raise ValueError("invalid scenario response identity")
            result = response["result"]
        except PermissionError:
            raise
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            if not scenario:
                raise
            from .android_execution_contract import uncertain_result
            code = ("transport_timeout" if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired))
                    else "transport_execution_uncertain")
            return uncertain_result(request["arguments"], payload["request_id"], code)
        if request.get("provider") == "android" and request.get("tool") == "scenario_run":
            from .android_invocation_trace import annotate_transport
            # The pinned transport already authenticates node and request ID.
            # Report correlation only on an actual matching envelope.
            if response.get("request_id") == payload["request_id"] and response.get("node") == node:
                result = annotate_transport(result, payload["request_id"], "watchtower_transport",
                                            (time.monotonic() - started) * 1000)
        return result
