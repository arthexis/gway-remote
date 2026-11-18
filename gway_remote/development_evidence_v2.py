"""Development evidence V2: offline, fail-closed adapters for existing read APIs.

No GitHub/host I/O, deployment calls, persistence, or MCP exposure.
Provenance identifies the *claimed* source of supplied data, not an attestation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .development_evidence import _sha, _time, deployment_receipt, development_snapshot
from .reconcile import TARGETS

_SOURCES = ("journal", "release", "github", "ci")
_DEFAULT_AGES = {"journal": 86400, "release": 300, "github": 300, "ci": 300}
_ALLOWED_CI = frozenset({"success", "failure", "pending", "unknown"})


def _clock(value):
    normalized = _time(value)
    if normalized is None:
        raise ValueError("invalid observation timestamp")
    return datetime.fromisoformat(normalized)


def _ages(max_age_seconds):
    values = _DEFAULT_AGES if max_age_seconds is None else max_age_seconds
    if (not isinstance(values, dict) or set(values) != set(_SOURCES) or
        any(type(v) is not int or v < 1 or v > 604800 for v in values.values())):
        raise ValueError("invalid source freshness policy")
    return values


def _observed(source, *, at, now, max_age_seconds, node, repository):
    time = _clock(at)
    skew = now - time
    # Clock skew and stale observations are not equivalent to negative proof.
    state = ("future" if skew < timedelta(0) else
             "stale" if skew > timedelta(seconds=max_age_seconds) else "fresh")
    return {"source": source, "node": node, "repository": repository,
            "observed_at": time.isoformat(), "freshness": state}


def development_evidence_v2(name, *, journal, status_report, github, observed_at,
                            now, max_age_seconds=None):
    """Project complete, caller-supplied snapshots from existing read mechanisms.

    journal: read_attempts() dict (authoritative only for recorded attempts).
    status_report: status(depth='deep') response from the owning local node.
    github: explicitly supplied {repository, head_sha, ci, head_observed_at,
            ci_observed_at, ci_head_sha}; adapters never fetch GitHub.
    observed_at: timestamp when the caller read the journal, not attempt['at'].
    Returns only allowlisted metadata; no errors/logs/secrets from source payloads.
    """
    targets = dict(TARGETS)
    if name not in targets:
        raise ValueError("unknown target")
    repository = targets[name]
    current = _clock(now)
    limits = _ages(max_age_seconds)
    if not isinstance(journal, dict) or not isinstance(status_report, dict) or not isinstance(github, dict):
        raise ValueError("invalid source snapshot")
    if github.get("repository") != repository or set(github) != {
        "repository", "head_sha", "ci", "head_observed_at", "ci_observed_at", "ci_head_sha"
    }:
        raise ValueError("invalid GitHub source identity")
    head = _sha(github["head_sha"])
    ci_head = _sha(github["ci_head_sha"])
    if head is None or ci_head is None or github["ci"] not in _ALLOWED_CI:
        raise ValueError("invalid GitHub evidence")
    if (status_report.get("schema") != "gway-remote/status/v1"
        or status_report.get("depth") != "deep"
        or status_report.get("node") != "gway-001"
        or not isinstance(status_report.get("components"), list)):
        raise ValueError("untrusted or incomplete local status envelope")
    matching = [r for r in status_report["components"] if isinstance(r, dict) and r.get("name") == name]
    if len(matching) != 1:
        raise ValueError("missing or duplicate release row")
    row = matching[0]
    evidence = row.get("deployment_evidence")
    if (not isinstance(evidence, dict)
        or evidence.get("repository") != repository
        or evidence.get("observed_at") != status_report.get("checked_at")):
        raise ValueError("inconsistent release provenance")
    attempt = journal.get(name)
    if attempt is not None and not isinstance(attempt, dict):
        raise ValueError("invalid attempt")
    sources = {
        "journal": _observed("attempts.json", at=observed_at, now=current,
                             max_age_seconds=limits["journal"], node="gway-001", repository=repository),
        "release": _observed("gway-remote/status/v1:deep", at=status_report["checked_at"],
                             now=current, max_age_seconds=limits["release"], node="gway-001", repository=repository),
        "github": _observed("github/main", at=github["head_observed_at"],
                            now=current, max_age_seconds=limits["github"], node=None, repository=repository),
        "ci": _observed("github/pr-ci", at=github["ci_observed_at"],
                        now=current, max_age_seconds=limits["ci"], node=None, repository=repository),
    }
    reasons = []
    if any(item["freshness"] != "fresh" for item in sources.values()):
        reasons.append("stale_or_future_observation")
    if head != ci_head:
        reasons.append("ci_revision_mismatch")
    if github["ci"] != "success":
        reasons.append("ci_not_successful")
    # Status installed_sha can be a 12-char release link. A prefix never proves
    # full SHA equality, and the journal must not be promoted to the release.
    raw_installed = row.get("installed_sha")
    installed = _sha(raw_installed)
    if raw_installed is not None and installed is None:
        reasons.append("installed_revision_not_full_sha")
    if evidence.get("installation_state") != "activated" or evidence.get("activated_revision") != raw_installed:
        reasons.append("activation_unverified")
    if installed is None:
        reasons.append("installed_revision_unknown")
    elif installed != head:
        reasons.append("installed_revision_differs")
    if row.get("health") != "healthy" or evidence.get("runtime_state") != "healthy":
        reasons.append("runtime_health_unverified")
    if attempt is None:
        receipt = None
        reasons.append("attempt_unknown")
    else:
        receipt = deployment_receipt(name, attempt, observed_sha=installed,
                                     health=row.get("health") if row.get("health") in
                                     ("healthy", "unhealthy", "unknown") else "unknown")
        if receipt["requested_sha"] != head:
            reasons.append("attempt_revision_differs")
    # Never claim operational acceptance: data come from supplied readouts.
    # A clean result is still only 'review'; separate live functional acceptance
    # and authenticated source provenance belong to V3.
    stage = "review" if not reasons else "unknown"
    return {
        "schema": "gway.development-evidence.v2",
        "target": name, "repository": repository, "stage": stage,
        "reasons": sorted(set(reasons)), "functional_acceptance": "unknown",
        "source_attestation": "unverified", "sources": sources,
        "github_head": head, "ci": github["ci"], "installed_sha": installed,
        "receipt": receipt,
    }
