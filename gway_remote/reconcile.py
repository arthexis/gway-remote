"""Pure appliance-wide deployment debounce policy.

No GitHub access, subprocesses, timers, or persistent state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import re
from typing import Sequence

QUIET_PERIOD = timedelta(minutes=20)
TARGETS = (
    ("ocpp-csms", "arthexis/ocpp-csms"),
    ("ocpp-simulator", "arthexis/ocpp-simulator"),
    ("gway-lcd-sound", "arthexis/gway-lcd-sound"),
)
_SHA = re.compile(r"[0-9a-fA-F]{40}")
_GOOD_CI = "success"


class Decision(str, Enum):
    WAITING = "waiting"
    BLOCKED = "blocked"
    UP_TO_DATE = "up-to-date"
    READY = "ready"


@dataclass(frozen=True)
class TargetState:
    name: str
    desired_sha: str
    deployed_sha: str | None
    main_updated_at: datetime | None
    ci_status: str


@dataclass(frozen=True)
class DeploymentTarget:
    name: str
    sha: str


@dataclass(frozen=True)
class DeploymentPlan:
    decision: Decision
    targets: tuple[DeploymentTarget, ...]
    desired_revisions: tuple[DeploymentTarget, ...]
    quiet_until: datetime | None
    reason: str


def _utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def reconcile(targets: Sequence[TargetState], now: datetime) -> DeploymentPlan:
    """Evaluate an entire appliance snapshot; fail closed on incomplete inputs.

    The caller supplies authoritative main-branch arrival timestamps, verified CI
    conclusions and deployed revisions. Missing deployed revisions require an
    explicit bootstrap in a later integration chunk.
    """
    now_utc = _utc(now)
    if now_utc is None:
        raise ValueError("now must be timezone-aware")

    by_name = {target.name: target for target in targets}
    expected = tuple(name for name, _ in TARGETS)
    snapshot = tuple(
        DeploymentTarget(name, by_name[name].desired_sha)
        for name in expected if name in by_name
    )
    def result(decision: Decision, reason: str, deadline: datetime | None = None,
               pending: tuple[DeploymentTarget, ...] = ()) -> DeploymentPlan:
        return DeploymentPlan(decision, pending, snapshot, deadline, reason)

    if len(targets) != len(expected) or set(by_name) != set(expected):
        return result(Decision.BLOCKED, "missing, duplicate, or unexpected target")
    if any(not _SHA.fullmatch(t.desired_sha) or
           (t.deployed_sha is not None and not _SHA.fullmatch(t.deployed_sha))
           for t in targets):
        return result(Decision.BLOCKED, "invalid revision SHA")
    if any(t.deployed_sha is None for t in targets):
        return result(Decision.BLOCKED, "unknown deployed revision; bootstrap required")
    if any(_utc(t.main_updated_at) is None for t in targets):
        return result(Decision.BLOCKED, "missing or naive main update timestamp")
    if any(_utc(t.main_updated_at) > now_utc for t in targets):
        return result(Decision.BLOCKED, "main update timestamp is in the future")

    changed = tuple(DeploymentTarget(name, by_name[name].desired_sha)
                    for name in expected
                    if by_name[name].desired_sha.lower() != by_name[name].deployed_sha.lower())
    if not changed:
        return result(Decision.UP_TO_DATE, "all desired revisions deployed")

    quiet_until = max(_utc(t.main_updated_at) for t in targets) + QUIET_PERIOD
    if now_utc < quiet_until:
        return result(Decision.WAITING, "shared quiet period has not elapsed", quiet_until)
    if any(by_name[t.name].ci_status != _GOOD_CI for t in changed):
        return result(Decision.BLOCKED, "required CI not successful", quiet_until)
    return result(Decision.READY, "validated appliance snapshot ready", quiet_until, changed)
