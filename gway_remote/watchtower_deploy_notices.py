"""Trusted Watchtower-side, receipt-bound Deploy Broker LCD/Sound notifier.

This is an INTERNAL service operation, not an untrusted source endpoint.
The caller already authenticated the execute principal and established an
immutable per-request node/application binding. We reuse Watchtower's
existing pinned node bridge; no bearer is minted or copied.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import hashlib
import os
import subprocess

from .deployment_lcd_notifications import document

# Explicit, reviewed mapping. Provider source names are NOT always GitHub
# repository names; unrecognized providers must not receive invented labels.
REPOSITORIES = {
    "ocpp_reports": "arthexis/ocpp-reports",
    "ocpp_csms": "arthexis/ocpp-csms",
    "gway_remote": "arthexis/gway-remote",
    "gway_agent_ops": "arthexis/gway-agent-ops",
    "gway_lcd_sound": "arthexis/gway-lcd-sound",
}
STATES = {"running": "deploy-started",
          "succeeded": "deploy-activated",
          "failed": "deploy-failed"}


def emit(application, node, request_id, state, *, dispatch=None, now=None):
    """One best-effort transition; the receiver's deterministic ID deduplicates.

    Unknown outcomes, missing explicit provider mapping or disabled flag are
    silent. This never changes a broker receipt or re-dispatches an installer.
    """
    if os.environ.get("GWAY_BROKER_LCD_NOTIFICATIONS") != "1":
        return False
    if application not in REPOSITORIES or state not in STATES:
        return False
    if type(request_id) is not str or len(request_id) != 32 or any(
            c not in "0123456789abcdef" for c in request_id):
        return False
    try:
        from .lcd_sound_bridge import dispatch as default_dispatch
        sender = dispatch if dispatch is not None else default_dispatch
        note = document(REPOSITORIES[application], node, STATES[state],
                        request_id, origin_node="gelectriic.com")
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            return False
        def event(device, action, arguments):
            key = ("trusted-watchtower-deployment-v1:" + request_id + ":" +
                   state + ":" + device)
            rid = hashlib.sha256(key.encode("ascii")).hexdigest()[:32]
            return {
                "schema": 1, "node": "gway-001", "origin": "watchtower",
                "request_id": rid,
                "expires_at": (now + timedelta(seconds=20)).isoformat(),
                "device": device, "action": action, "arguments": arguments,
                "hops": 0,
            }
        result = sender(event("lcd", "notice", {"notice": note}))
        delivered = type(result) is dict and result.get("status") == "succeeded"
        if state == "failed":
            sender(event("sound", "play", {"name": "error"}))
        return delivered
    except (OSError, RuntimeError, PermissionError, ValueError, TypeError,
            subprocess.SubprocessError):
        return False
