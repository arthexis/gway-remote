"""V3 operational acceptance over pre-existing read-only deployment receipts.

Pure projection: no I/O, authentication, deployment, services, ledgers, or
additional permissions. Inputs must be collected by already authorized readers.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .development_evidence import _sha, _time


_REQUIRED_JOBS = frozenset({
    "Classify push impact (hosted, read-only)",
    "deploy",
    "Deploy Watchtower MCP",
})
_NODES = frozenset({"gway-001", "Watchtower"})
_WATCHTOWER_UNITS = frozenset({
    "gway-mcp-gateway.service",
    "gway-mcp-link.service",
    "gway-remote-watchtower-enroll.service",
})


def _timestamp(value):
    normalized = _time(value)
    if normalized is None:
        raise ValueError("invalid observation timestamp")
    return datetime.fromisoformat(normalized)


def _fresh(value, current, ttl):
    t = _timestamp(value)
    if t > current:
        return "future"
    return "fresh" if current - t <= timedelta(seconds=ttl) else "stale"


def operational_acceptance_v3(*, revision, workflow, nodes, observed_at,
                              now, ttl_seconds=300):
    """Evaluate an exact completed backend push workflow and two node reads.

    workflow: existing GitHub run {head_sha,event,status,conclusion,jobs},
      each job has {name,status,conclusion}. This is an existing CI receipt,
      not an authorization to deploy.
    nodes: existing read-only observations keyed by gway-001 and Watchtower:
      {active_revision, previous_revision, observed_at, status} with Watchtower
      also containing {services: {unit: "active"}}. Gway status is the
      existing gway-remote/status/v1 deep report, health checks are not
      invented by this projection. The source identity is declared, not signed.
    """
    if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 604800:
        raise ValueError("invalid TTL")
    sha = _sha(revision)
    if sha is None or not isinstance(workflow, dict) or not isinstance(nodes, dict):
        raise ValueError("invalid operational evidence")
    if set(nodes) != _NODES:
        raise ValueError("incomplete node inventory")
    current = _timestamp(now)
    reasons = []
    if _fresh(observed_at, current, ttl_seconds) != "fresh":
        reasons.append("workflow_receipt_stale_or_future")

    if (workflow.get("event") != "push"
        or workflow.get("head_sha") != sha
        or workflow.get("status") != "completed"
        or workflow.get("conclusion") != "success"):
        reasons.append("workflow_not_verified")
    jobs = workflow.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("missing workflow jobs")
    names = [j.get("name") if isinstance(j, dict) else None for j in jobs]
    if len(names) != len(_REQUIRED_JOBS) or set(names) != _REQUIRED_JOBS:
        reasons.append("workflow_jobs_incomplete")
    if any(not isinstance(j, dict) or j.get("status") != "completed"
           or j.get("conclusion") != "success" for j in jobs):
        reasons.append("workflow_jobs_not_successful")

    states = {}
    for node in ("gway-001", "Watchtower"):
        entry = nodes[node]
        if not isinstance(entry, dict):
            raise ValueError("invalid node evidence")
        time_state = _fresh(entry.get("observed_at"), current, ttl_seconds)
        if time_state != "fresh":
            reasons.append(node.lower() + "_observation_stale_or_future")
        active = _sha(entry.get("active_revision"))
        previous = _sha(entry.get("previous_revision"))
        if active != sha:
            reasons.append(node.lower() + "_active_release_mismatch")
        if previous is None or previous == active:
            reasons.append(node.lower() + "_rollback_unverified")
        health = entry.get("status")
        if node == "gway-001":
            if (not isinstance(health, dict)
                or health.get("schema") != "gway-remote/status/v1"
                or health.get("node") != "gway-001"
                or health.get("depth") != "deep"
                or not isinstance(health.get("components"), list)
                or not health.get("components")):
                reasons.append("gway-001_health_unverified")
        else:
            units = entry.get("services")
            if (not isinstance(units, dict) or set(units) != _WATCHTOWER_UNITS
                or any(state != "active" for state in units.values())):
                reasons.append("watchtower_services_unverified")
        states[node] = {"active_revision": active,
                        "previous_revision": previous,
                        "observed_at": _timestamp(entry["observed_at"]).isoformat(),
                        "freshness": time_state}

    return {
        "schema": "gway.operational-acceptance.v3",
        "revision": sha,
        "state": "accepted" if not reasons else "unknown",
        "reasons": sorted(set(reasons)),
        "node_observations": states,
        "receipt_observed_at": _timestamp(observed_at).isoformat(),
        "source_authentication": "existing_reader_only",
        "deployment_authorization": "not_applicable",
    }
