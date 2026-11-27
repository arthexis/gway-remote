"""Narrow JSON-over-stdin node protocol for a future SSH forced command.

Not installed in authorized_keys and not reachable through MCP. Must run under
the existing locked-down gway-exec identity, via an explicitly reviewed
forced-command setup; never execute arbitrary SSH_ORIGINAL_COMMAND.
"""
import json
import os
import re
import socket
import subprocess
import sys
import time

from .node_exec_worker import Jobs, configured_max_active, require_account, validate_request_id
from .node_exec_contract import validate_command, RELAY_ONLY_NODE, RELAY_ONLY_OPERATIONS

MAX_REQUEST_BYTES = 65536
OPERATIONS = {
    "periodic_health_submit": frozenset({"operation", "node", "request_id"}),
    "periodic_health_result": frozenset({"operation", "node", "request_id"}),
    "probe_provision_status": frozenset({"operation","node","request_id"}),
    "probe_provision_install": frozenset({"operation","node","request_id","credential"}),
    "feed_provision_status": frozenset({"operation","node","request_id"}),
    "feed_provision_install": frozenset({"operation","node","request_id","principal","credential"}),
    "lcd_sound_event": frozenset({"operation", "node", "request_id", "event"}),
    "submit": frozenset({"operation", "node", "request_id", "command"}),
    "health_probe_submit": frozenset({"operation", "node", "request_id"}),
    "health_probe_result": frozenset({"operation", "node", "request_id"}),
    "result": frozenset({"operation", "node", "request_id", "cursor"}),
    "cancel": frozenset({"operation", "node", "request_id"}),
    "limits": frozenset({"operation", "node", "request_id"}),
    "file_read": frozenset({"operation", "node", "request_id", "filename", "offset"}),
    "workspace_inspect": frozenset({"operation", "node", "request_id", "repository"}),
    "deployment_discovery": frozenset({"operation", "node", "request_id"}),
    "deployment_preview": frozenset({"operation", "node", "request_id", "application"}),
    "deployment_status": frozenset({"operation", "node", "request_id", "application"}),
    "deployment_run": frozenset({"operation", "node", "request_id", "application", "expected_revision"}),
    "provider_list": frozenset({"operation", "node", "request_id"}),
    # Operation-bound read contract: no forwarded OAuth token or scope. The
    # owning node checks the current tool declaration before dispatch.
    "provider_read": frozenset({"operation", "node", "request_id", "provider", "tool", "arguments"}),
    "provider_call": frozenset({"operation", "node", "request_id", "provider", "tool", "arguments"}),
}


from .mcp_owner_bound_wire import OPS as OWNER_OPS, FIELDS as OWNER_FIELDS
OPERATIONS.update({op: frozenset(OWNER_FIELDS) for op in OWNER_OPS})
from .agentops_coordination import OPS as COORDINATION_OPS
OPERATIONS.update(COORDINATION_OPS)

def serve_one(raw, *, jobs=None, hostname=None, trusted_relay=False):
    """One message per process, no interactive shell or arbitrary Python calls."""
    require_account()
    if type(raw) is not bytes or len(raw) > MAX_REQUEST_BYTES:
        raise ValueError("oversized request")
    try:
        req = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("invalid request JSON") from None
    if type(req) is not dict or req.get("operation") not in OPERATIONS:
        raise ValueError("invalid operation")
    op = req["operation"]
    fields = set(req)
    if fields != OPERATIONS[op]:
        raise ValueError("invalid request fields")
    host = hostname if hostname is not None else socket.gethostname()
    if (not re.fullmatch(r"gway-[0-9]+", host) and host != RELAY_ONLY_NODE) or req["node"] != host:
        raise PermissionError("unapproved node")
    if host == RELAY_ONLY_NODE and op not in RELAY_ONLY_OPERATIONS:
        raise PermissionError("relay-only node operation denied")
    rid = validate_request_id(req["request_id"])
    if op in ("submit", "result", "cancel"):
        from .periodic_health_contract import slot_for
        if slot_for(host, rid) is not None:
            raise PermissionError("periodic probe identity reserved")
    if op in ('probe_provision_status','probe_provision_install'):
        from .node_exec_identity import selected_user
        if host!='gway-001' or selected_user()!='arthe':raise PermissionError('probe provision target or owner denied')
        from .probe_provision_node import deliver
        result=deliver(op,req.get('credential'))
        return {'node':host,'request_id':rid,'result':result}
    if op in ("feed_provision_status", "feed_provision_install"):
        from .activity_feed_provision_node import status, install
        result = status(host) if op == "feed_provision_status" else install(host, req["principal"], req["credential"])
        return {"node": host, "request_id": rid, "result": result}
    if op == "lcd_sound_event":
        from .lcd_sound_event import receive
        from .node_exec_identity import executor_path, selected_user
        event = req["event"]
        if type(event) is not dict or event.get("request_id") != rid:
            raise ValueError("event request mismatch")
        result = receive(event, trusted_node=host,
                         command_path=executor_path(selected_user()))
        return {"node": host, "request_id": rid, "result": result}
    if op == "file_read":
        # Preserve the operator executor identity for all existing operations.
        # Only the exact, sudoers-pinned reader crosses into gway-exec.
        if host != "gway-001":
            raise PermissionError("file export not provisioned for node")
        payload = json.dumps({"node": host, "request_id": rid,
                              "filename": req["filename"], "offset": req["offset"]},
                             separators=(",", ":")).encode("utf-8")
        argv = ["/usr/bin/sudo", "-n", "-u", "gway-exec",
                "/usr/bin/env", "PYTHONPATH=/opt/gway-remote",
                "/usr/bin/python3", "-m", "gway_remote.node_file_reader"]
        try:
            completed = subprocess.run(argv, input=payload, capture_output=True,
                                       check=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            raise PermissionError("file reader unavailable") from None
        if len(completed.stdout) > 16384:
            raise PermissionError("file reader response too large")
        response = json.loads(completed.stdout)
        if (type(response) is not dict or set(response) != {"node", "request_id", "result"}
                or response["node"] != host or response["request_id"] != rid
                or type(response["result"]) is not dict):
            raise PermissionError("uncorrelated file reader response")
        return response
    if op == "workspace_inspect":
        # Bind to the trusted forced-command hostname; resolve paths solely
        # from the existing node-owned provider and workspace registries.
        from .mcp_workspace_inspect import inspect_authorized
        result = inspect_authorized({"node": host, "repository": req["repository"]},
                                    trusted_node=host)
        return {"node": host, "request_id": rid, "result": result}
    if op == "deployment_discovery":
        from .mcp_deployment_resolver import deployment_catalog
        try:
            result = deployment_catalog()
        except (ValueError, PermissionError, OSError):
            return {"node": host, "request_id": rid, "error": "deployment_declaration_invalid"}
        return {"node": host, "request_id": rid, "result": result}
    if op in ("deployment_preview", "deployment_status", "deployment_run"):
        from .mcp_deployment_broker import preview, request_status, accept
        from .mcp_deployment_resolver import deployment_error_code
        try:
            if op == "deployment_preview":
                result = preview(req["application"])
            elif op == "deployment_status":
                result = request_status(req["application"], rid)
            else:
                result = accept(req["application"], rid, expected_revision=req["expected_revision"])
        except (ValueError, PermissionError, OSError) as exc:
            return {"node": host, "request_id": rid, "error": deployment_error_code(exc)}
        return {"node": host, "request_id": rid, "result": result}
    if op in COORDINATION_OPS:
        if trusted_relay is not True:
            raise PermissionError("coordination_requires_trusted_relay")
        from .agentops_coordination import node_exchange
        return {"node":host,"request_id":rid,"result":node_exchange(host,req)}
    if op in OWNER_OPS:
        if trusted_relay is not True:
            raise PermissionError("owner_rpc_requires_trusted_relay")
        from .mcp_owner_bound_wire import validate, reserve
        from .mcp_installed_providers import discover_installed_providers
        from .mcp_node_providers import provider_call
        scope = validate(req, host)
        reserve(req)
        result = provider_call(discover_installed_providers(), provider=req["provider"],
                               tool=req["tool"], arguments=req["arguments"],
                               authorized_scope=scope, verified_principal=req["principal"])
        return {"node": host, "request_id": rid, "result": result}
    if op in ("provider_list", "provider_call", "provider_read"):
        from .mcp_node_providers import dispatch_node_provider_request
        from .mcp_installed_providers import discover_installed_providers
        registrations = discover_installed_providers()
        if op == "provider_list":
            request, scope = {"operation": "provider_list"}, "read"
        elif op == "provider_read":
            # Stage B/P3: the verb itself requests only a read operation;
            # validate the LIVE declaration on the node. This is operation
            # semantics, not a second check of the bearer identity.
            scope = "read"
            request = {key: req[key] for key in ("provider", "tool", "arguments")}
            request["operation"] = "provider_call"
        else:
            # The authenticated SSH verb, never a caller-supplied field,
            # chooses execution semantics. Reads use provider_read.
            scope = "execute"
            request = {key: req[key] for key in ("provider", "tool", "arguments")}
            request["operation"] = "provider_call"
        options = {"node_id": host, "trusted_scope": scope}
        android_call = request.get("provider") == "android"
        started = time.monotonic()
        if android_call or request.get("provider") == "agentops":
            options["invocation_id"] = rid
        result = dispatch_node_provider_request(registrations, request, **options)
        if android_call and request.get("tool") == "scenario_run":
            from .android_invocation_trace import annotate_transport
            result = annotate_transport(result, rid, "node_transport",
                                        (time.monotonic() - started) * 1000)
        return {"node": host, "request_id": rid, "result": result}
    if op == "limits":
        return {"node": host, "request_id": rid,
                "concurrent_jobs_per_node": configured_max_active()}
    if jobs is None:
        jobs = Jobs()
    if op in ('periodic_health_submit', 'periodic_health_result'):
        from .periodic_health_contract import COMMAND, validate_probe
        slot = validate_probe(host, rid, submit=op == 'periodic_health_submit')
        if op == 'periodic_health_submit':
            try:
                jobs.submit(host, COMMAND, request_id=rid, periodic_slot=slot)
            except RuntimeError as exc:
                if str(exc) == 'executor busy':
                    return {'node':host,'request_id':rid,'status':'busy'}
                if str(exc) == 'executor user manager unavailable':
                    return {'node':host,'request_id':rid,'status':'failed'}
                raise
            return {'node':host,'request_id':rid,'status':'accepted'}
        return jobs.periodic_result(host, rid)
    if op in ('health_probe_submit', 'health_probe_result'):
        from .mcp_health_probe_contract import NODE, nonce_command, project_result
        if host != NODE:
            raise PermissionError('probe_node_denied')
        command = nonce_command(rid)
        if op == 'health_probe_submit':
            try:
                jobs.submit(host, command, request_id=rid,health_probe=True)
            except RuntimeError as exc:
                if str(exc) == 'executor user manager unavailable':
                    return {'node':host,'request_id':rid,'status':'rejected','failure_stage':'worker_readiness'}
                raise
            return {'node':host,'request_id':rid,'status':'accepted'}
        return jobs.probe_result(rid)
    if op == "submit":
        validate_command(host, req["command"])
        try:
            jobs.submit(host, req["command"], request_id=rid)
        except RuntimeError as exc:
            # Only an exact, locally proven worker-readiness condition is typed.
            # Never send exception text, commands or host configuration.
            if str(exc) == "executor user manager unavailable":
                return {"node": host, "request_id": rid, "status": "rejected",
                        "failure_stage": "worker_readiness"}
            raise
        return {"node": host, "request_id": rid, "status": "accepted"}
    if op == "result":
        cursor = req["cursor"]
        if type(cursor) is not int or cursor < 0:
            raise ValueError("invalid cursor")
        result = jobs.result(rid, cursor)
        if result["node"] != host:
            raise PermissionError("job belongs to another node")
        return result
    row = jobs.row(rid)
    if row["node"] != host:
        raise PermissionError("job belongs to another node")
    return {"node":host, "request_id":rid, "status":jobs.cancel(rid)}


def main():
    # SSH dispatch is not enabled by installing this module. When connected to
    # SSH, the operator must independently bind a fixed, dedicated key to this
    # module and restrict forwarding, PTY and environment.
    try:
        # sudo sets this for the fixed gway-relay transition. This is not
        # an isolation mechanism against the trusted local installation user.
        import pwd
        try:
            relay = pwd.getpwnam("gway-relay")
            trusted = (os.environ.get("SUDO_USER") == relay.pw_name
                       and os.environ.get("SUDO_UID") == str(relay.pw_uid))
        except KeyError:
            trusted = False
        result = serve_one(sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1),
                           trusted_relay=trusted)
        print(json.dumps(result, separators=(",", ":")))
        return 0
    except (ValueError, PermissionError, RuntimeError, OSError):
        # Never return raw command, stderr secrets, filesystem paths or tokens.
        print(json.dumps({"error":"node operation rejected"}, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    sys.exit(main())
