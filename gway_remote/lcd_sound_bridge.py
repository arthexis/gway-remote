"""Watchtower-side hardware-event bridge via existing pinned node transport.

Only an OS account already permitted to read the root-controlled Watchtower
execution configuration and SSH identity can dispatch. There is no new listener,
credential, fallback destination or SSH shell command.
"""
from __future__ import annotations
import argparse
import json
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
    service = (load or load_service)()
    transport = service.relay.transport
    # Idempotent receiver journal makes exact-ID retry safe even if the
    # connection drops AFTER the remote hardware operation.
    req = {"operation": "lcd_sound_event", "node": node,
           "request_id": event["request_id"], "event": event}
    for attempt in range(2):
        try:
            response = transport.invoke(req)
        except (SSHTransportFailure, OSError):
            if attempt == 0:
                sleep(0.2)
                continue
            raise RuntimeError("remote outcome uncertain") from None
        result = response.get("result")
        if type(result) is not dict or result.get("status") not in ("succeeded", "failed", "uncertain"):
            raise RuntimeError("invalid receiver acknowledgement")
        return {"node": node, "request_id": event["request_id"],
                "status": result["status"], "duplicate": result.get("duplicate") is True}
    raise RuntimeError("remote event not acknowledged")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="gway-remote lcd-sound send")
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read(8193)
        if len(raw) > 8192:
            raise ValueError("oversized event")
        event = json.loads(raw)
        result = dispatch(event)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "succeeded" else 1
    except (OSError, RuntimeError, PermissionError, ValueError, TypeError, KeyError):
        print("lcd-sound: event delivery unavailable", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
