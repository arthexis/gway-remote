"""Watchtower-side hardware-event bridge via existing pinned node transport.

Only an OS account already permitted to read the root-controlled Watchtower
execution configuration and SSH identity can dispatch. There is no new listener,
credential, fallback destination or SSH shell command.
"""
from __future__ import annotations
import argparse
import json
import secrets
import subprocess
import sys
import time

from .lcd_sound_event import validate


def dispatch(event, *, load=None, sleep=time.sleep):
    from .node_registry_inventory import load as load_inventory
    from .watchtower_exec_service import load_service
    from .watchtower_exec_transport import SSHTransportFailure
    inventory = load_inventory()
    if type(event) is not dict:
        raise ValueError("invalid event")
    node = event.get("node")
    eligible = [row for row in inventory["nodes"]
                if row.get("node") == node and row.get("registered") is True
                and row.get("identity_verified") is True
                and row.get("execute_eligible") is True
                and row.get("reachable") == "reachable"]
    if len(eligible) != 1:
        raise PermissionError("node not eligible or reachable")
    validate(event, trusted_node=node)
    if event["origin"] != "watchtower":
        raise PermissionError("sender identity must match trusted Watchtower endpoint")
    service = (load or load_service)()
    transport = service.relay.transport
    # Idempotent receiver journal makes exact-ID retry safe even if the
    # connection drops AFTER the remote hardware operation.
    req = {"operation": "lcd_sound_event", "node": node,
           "request_id": event["request_id"], "event": event}
    for attempt in range(2):
        try:
            response = transport.invoke(req)
        except (SSHTransportFailure, OSError, subprocess.SubprocessError):
            if attempt == 0:
                sleep(0.2)
                continue
            raise RuntimeError("remote outcome uncertain") from None
        result = response.get("result")
        if type(result) is not dict or result.get("status") not in ("succeeded", "failed", "uncertain"):
            raise RuntimeError("invalid receiver acknowledgement")
        answer = {"node": node, "request_id": event["request_id"],
                  "status": result["status"], "duplicate": result.get("duplicate") is True}
        # Readback from status, public --dry-run and --resolve must survive
        # the pinned relay unchanged. The sender never receives receiver stdout
        # for a physical event unless it explicitly requested a bounded preview.
        wants_output = (event["action"] == "status"
                        or event["arguments"].get("dry_run") is True
                        or event["arguments"].get("resolve") is True)
        if wants_output and result["status"] == "succeeded":
            output = result.get("output")
            if type(output) is not str or len(output.encode("utf-8")) > 4096:
                raise RuntimeError("missing or unbounded receiver preview")
            answer["output"] = output
        return answer
    raise RuntimeError("remote event not acknowledged")


def probe(node, *, load=None):
    from .node_registry_inventory import load as load_inventory
    from .watchtower_exec_service import load_service
    from .node_exec_contract import validate_command
    validate_command(node, "true")
    inventory = load_inventory()
    rows = [r for r in inventory["nodes"] if r.get("node") == node
            and r.get("registered") is True and r.get("identity_verified") is True
            and r.get("execute_eligible") is True and r.get("reachable") == "reachable"]
    if len(rows) != 1:
        raise PermissionError("node not eligible")
    service = (load or load_service)()
    rid = secrets.token_hex(16)
    response = service.relay.transport.invoke({"operation": "limits", "node": node, "request_id": rid})
    if response.get("node") != node or response.get("request_id") != rid or type(response.get("concurrent_jobs_per_node")) is not int:
        raise RuntimeError("pinned node verification failed")
    return {"node": node, "status": "eligible", "transport": "pinned_ssh"}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="gway-remote lcd-sound send")
    parser.add_argument("operation", choices=("send", "probe"))
    parser.add_argument("node", nargs="?")
    args = parser.parse_args(argv)
    try:
        if args.operation == "probe":
            if args.node is None:
                raise ValueError("missing node")
            print(json.dumps(probe(args.node), sort_keys=True))
            return 0
        if args.node is not None:
            raise ValueError("unexpected node")
        raw = sys.stdin.buffer.read(8193)
        if len(raw) > 8192:
            raise ValueError("oversized event")
        event = json.loads(raw)
        result = dispatch(event)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "succeeded" else 1
    except (OSError, RuntimeError, PermissionError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        print("lcd-sound: event delivery unavailable", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
