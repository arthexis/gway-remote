"""Fail-closed, read-only Fleet v1 projection. No node commands or network access.

The caller supplies independently authenticated observations; absence is unknown.
"""
from datetime import datetime, timezone
import re

SCHEMA = "gway-remote/fleet/v1"
HARDWARE = "gway-remote/hardware/v1"
STATUS = "gway-remote/status/v1"
MAX_NODES = 100
MAX_AGE_SECONDS = 300


def _fresh(doc, schema, now):
    if not isinstance(doc, dict) or doc.get("schema") != schema:
        return None
    try:
        stamp = datetime.fromisoformat(doc["checked_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None or not 0 <= (now - stamp).total_seconds() <= MAX_AGE_SECONDS:
            return None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    return doc


def project(inventory, observations=None, *, now=None):
    """Project an authoritative node_list and trusted per-node observations.

    observations are supplied by an authenticated transport, never by the TV.
    This function does not fetch, probe, execute or infer installation.
    """
    now = now or datetime.now(timezone.utc)
    if not isinstance(inventory, dict) or inventory.get("source") != "watchtower-enrollment-ledger":
        raise ValueError("untrusted fleet inventory")
    rows = inventory.get("nodes")
    if not isinstance(rows, list) or len(rows) > MAX_NODES:
        raise ValueError("invalid fleet inventory")
    if not isinstance(inventory.get("generated_at"), str):
        raise ValueError("missing inventory timestamp")
    try:
        stamp = datetime.fromisoformat(inventory["generated_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None or not 0 <= (now - stamp).total_seconds() <= 120:
            raise ValueError("stale inventory")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invalid inventory timestamp") from exc
    observations = observations if observations is not None else {}
    if not isinstance(observations, dict):
        raise ValueError("invalid observations")
    result = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("node"), str):
            raise ValueError("invalid node")
        name = row["node"]
        if not re.fullmatch(r"gway-[0-9]+", name) or name in seen:
            raise ValueError("duplicate or invalid node")
        seen.add(name)
        docs = observations.get(name) or {}
        if row.get("identity_verified") is not True:
            docs = {}
        if not isinstance(docs, dict):
            docs = {}
        hw = _fresh(docs.get("hardware"), HARDWARE, now)
        status = _fresh(docs.get("status"), STATUS, now)
        host = hw.get("host", {}) if hw else {}
        if not isinstance(host, dict):
            host = {}
        components = status.get("components", []) if status else []
        if not isinstance(components, list):
            components = []
        result.append({
            "node": name,
            "identity_verified": row.get("identity_verified") is True,
            "reachable": row.get("reachable") if row.get("reachable") in ("reachable", "unknown") else "unknown",
            "observed_at": row.get("observed_at"),
            "hardware": {"available": hw is not None, "observed_at": hw.get("checked_at") if hw else None,
                         "source": HARDWARE if hw else None,
                         "data": {key: host.get(key) for key in ("cpu_count", "cpu_frequency_mhz", "cpu_temperature_c", "memory", "root_filesystem", "uptime_seconds")} if hw else None},
            "services": {"available": status is not None, "observed_at": status.get("checked_at") if status else None,
                         "source": STATUS if status else None,
                         "components": [{"name": c.get("name"), "health": c.get("health", "unknown")} for c in components[:50] if isinstance(c, dict)]},
            "deployments": {"available": status is not None, "observed_at": status.get("checked_at") if status else None,
                            "source": STATUS if status else None,
                            "components": [{"name": c.get("name"), "installed_sha": c.get("installed_sha"),
                                            "deployment_evidence": c.get("deployment_evidence")} for c in components[:50] if isinstance(c, dict)]}
        })
    return {"schema": SCHEMA, "source": "watchtower-enrollment-ledger",
            "generated_at": now.isoformat(), "nodes": result}
