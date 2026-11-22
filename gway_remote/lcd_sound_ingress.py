"""Watchtower-side *programmatic* ingress for independently authenticated sources.

No HTTP listener, secrets, identity minting or SSH access for external hosts.
The invoking trusted application MUST authenticate its caller and pass a
principal derived exclusively from its verified auth context. A separate
deployment stage must connect this adapter to a restricted existing service.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from .lcd_sound_source_policy import authorize


def forward_authenticated(event, *, authenticated_principal, operator_grants,
                          dispatch=None):
    """Authorize the claimed source before using Watchtower's pinned relay.

    The node SSH session authenticates *Watchtower*, so the forwarded envelope
    is explicitly stamped `watchtower`; it is never pretended that the
    external host can authenticate directly to the node. The ingress receipt
    preserves the original source and the payload hash for operator auditing.
    Receiver dedup remains keyed by the unchanged request ID.
    """
    binding = authorize(event, verified_principal=authenticated_principal,
                        grants=operator_grants)
    original = json.dumps(event, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False).encode("utf-8")
    canonical = deepcopy(event)
    canonical["origin"] = "watchtower"
    # Deliberately use the existing constrained pinned transport; the
    # receiver must not grant arbitrary external hosts node SSH authority.
    if dispatch is None:
        from .lcd_sound_bridge import dispatch as dispatch_bridge
        dispatch = dispatch_bridge
    answer = dispatch(canonical)
    if (type(answer) is not dict or answer.get("node") != event["node"]
            or answer.get("request_id") != event["request_id"]
            or answer.get("status") not in ("succeeded", "failed", "uncertain")):
        raise RuntimeError("untrusted relay acknowledgment")
    result = dict(answer)
    result["source"] = binding["source"]
    result["source_event_sha256"] = hashlib.sha256(original).hexdigest()
    return result
