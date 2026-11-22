"""Pure per-source authorization for prospective authenticated LCD/Sound ingress.

THIS IS NOT an authentication mechanism or a network endpoint. The caller MUST
supply a principal from a verified transport/OAuth context (never an event
field or HTTP header) and an operator-controlled grant snapshot. The receiver
remains Watchtower-only until a separately reviewed ingress binds this policy
to its trusted SSH relay. No fallback to generic shell execution is permitted.
"""
from __future__ import annotations

import re

from .lcd_sound_event import ALLOWED, validate

PRINCIPAL = re.compile(r"[a-zA-Z0-9_.:@/-]{1,160}$")
SOURCE = re.compile(r"[a-z0-9][a-z0-9.-]{0,127}$")
TARGET = re.compile(r"gway-[0-9]{3,}$")


def authorize(event, *, verified_principal, grants):
    """Validate a caller-bound event against an explicit enabled source grant.

    grants: exact dict keyed by authenticated principal, values:
       {"source": str, "targets": [str], "operations": ["lcd.show", ...],
        "enabled": bool}
    Both provenance and storage/permissions of grants are an ingress concern.
    Never call with a client-supplied `verified_principal` or untrusted grants.
    """
    if (type(verified_principal) is not str
            or not PRINCIPAL.fullmatch(verified_principal)):
        raise PermissionError("missing trusted source principal")
    if type(grants) is not dict:
        raise PermissionError("unavailable trusted source grants")
    grant = grants.get(verified_principal)
    if type(grant) is not dict or set(grant) != {
        "source", "targets", "operations", "enabled"
    } or grant["enabled"] is not True:
        raise PermissionError("source not authorized")
    source = grant["source"]
    if type(source) is not str or not SOURCE.fullmatch(source) or source == "watchtower":
        raise PermissionError("invalid external source grant")
    targets, operations = grant["targets"], grant["operations"]
    if (type(targets) is not list or not targets
            or len(targets) != len(set(targets))
            or any(type(n) is not str or not TARGET.fullmatch(n) for n in targets)
            or type(operations) is not list or not operations
            or len(operations) != len(set(operations))
            or any(type(op) is not str or op not in {
                f"{dev}.{action}" for dev, actions in ALLOWED.items()
                for action in actions
            } for op in operations)):
        raise PermissionError("invalid source restrictions")
    if type(event) is not dict:
        raise ValueError("invalid event")
    if event.get("origin") != source or event.get("node") not in targets:
        raise PermissionError("event origin or target not authorized")
    if f'{event.get("device")}.{event.get("action")}' not in operations:
        raise PermissionError("source operation not authorized")
    # Full expiry, size, nonce, destination and allowlist validation is shared
    # with the existing receiver. It does NOT authenticate the principal.
    validate(event, trusted_node=event["node"], trusted_origin=source)
    return {"source": source, "node": event["node"],
            "principal": verified_principal}
