"""Pure best-effort policy: failed revisions require explicit owner retry."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .reconcile import TARGETS

QUIET_PERIOD = timedelta(minutes=10)


@dataclass(frozen=True)
class Candidate:
    name: str
    sha: str
    merged_at: datetime
    ci: str
    attempted_sha: str | None = None


@dataclass(frozen=True)
class Plan:
    state: str
    pending: tuple[tuple[str, str], ...]
    reason: str


def plan(candidates, now, *, bypass_quiet=False):
    """An unknown attempt is eligible once; failed or interrupted attempts need explicit retry."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    by_name = {c.name: c for c in candidates}
    names = tuple(name for name, _ in TARGETS)
    if len(candidates) != len(names) or set(by_name) != set(names):
        return Plan("blocked", (), "incomplete appliance snapshot")
    from .reconcile import _SHA
    for c in candidates:
        if (not _SHA.fullmatch(c.sha) or
                c.merged_at is None or c.merged_at.tzinfo is None or
                c.merged_at.utcoffset() is None):
            return Plan("blocked", (), "invalid revision or merge timestamp")
    pending = tuple((name, by_name[name].sha) for name in names
                    if by_name[name].attempted_sha != by_name[name].sha)
    if not pending:
        return Plan("idle", (), "all current revisions already attempted")
    latest = max(c.merged_at.astimezone(timezone.utc) for c in candidates)
    if not bypass_quiet and now.astimezone(timezone.utc) < latest + QUIET_PERIOD:
        return Plan("waiting", (), "shared quiet period")
    if any(by_name[name].ci != "success" for name, _ in pending):
        return Plan("blocked", (), "CI not successful for pending revision")
    return Plan("ready", pending, "one best-effort attempt per pending revision")
