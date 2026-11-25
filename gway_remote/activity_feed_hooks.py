"""Quiet, independently enabled lifecycle hooks; never flush or invoke hardware."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re

DEPLOY = {
    "started": ("Deployment started", "info"),
    "activated": ("Deployment activated", "info"),
    "verified": ("Deployment verified", "success"),
    "failed": ("Deployment failed", "error"),
    "uncertain": ("Deployment outcome uncertain", "warning"),
    "skipped": ("Deployment already current", "info"),
    "rollback_started": ("Rollback started", "warning"),
    "rollback_verified": ("Rollback verified", "success"),
    "rollback_failed": ("Rollback failed", "error"),
}
FLEET = {"down": ("Service down", "error"), "unreachable": ("Node unreachable", "warning"),
         "degraded": ("Service probe degraded", "warning"), "recovered": ("Service recovered", "success")}
NODE = re.compile(r"(?:gway-[0-9]{3,}|ocpp-abb-1|gelectriic\.com)\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


def enabled():
    if os.environ.get("GWAY_ACTIVITY_FEED_HOOKS") == "1":
        return True
    try:
        from .activity_feed_cli import read_private
        return read_private(Path.home() / ".config/gway-remote/feed-hooks.enabled", 16).strip() == b"enabled"
    except (OSError, ValueError):
        return False


def _id(*parts):
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


def event(*, source, kind, identity, at, title, summary, category, severity, **data):
    from .activity_feed import validate_event
    return validate_event({"specversion": "1.0", "id": _id(kind, identity),
                           "source": source, "type": kind, "time": at,
                           "data": {"title": title, "summary": summary, "category": category,
                                    "severity": severity, **data}})


def publish(build):
    """Local bounded SQLite enqueue; missing configuration cannot fail work."""
    try:
        if not enabled():
            return False
        from .activity_feed_cli import load_config, route_binding, STATE
        from .activity_feed_outbox import Outbox, publish_best_effort
        config = load_config()
        value = build(config["source"])
        if value is None:
            return False
        return publish_best_effort(Outbox(STATE, binding=route_binding(config)), value)
    except Exception:
        return False


def deployment(source, *, repository, node, attempt, state, at, sha=None):
    if not isinstance(repository, str) or not REPO.fullmatch(repository) or not isinstance(node, str) or not NODE.fullmatch(node):
        raise ValueError("invalid deployment identity")
    if not isinstance(attempt, str) or not attempt or len(attempt) > 256 or state not in DEPLOY:
        raise ValueError("invalid deployment transition")
    title, severity = DEPLOY[state]
    fields = {"repository": repository, "node": node, "correlation_id": _id("deploy", attempt)}
    if sha is not None and not state.startswith("rollback"):
        if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{40}", sha):
            raise ValueError("invalid revision")
        fields["commit"] = sha
    return event(source=source, kind="deployment." + state,
                 identity=(node, repository, attempt), at=at, title=title,
                 summary=repository + " on " + node, category="deployment", severity=severity, **fields)


def broker(application, node, attempt, state, at, sha=None):
    from .watchtower_deploy_notices import REPOSITORIES
    repository = REPOSITORIES.get(application)
    if repository is None:
        return False
    return publish(lambda source: deployment(source, repository=repository, node=node,
                   attempt=attempt, state=state, at=at, sha=sha))


def fleet_transition(source, *, node, service, state, episode, at):
    if not NODE.fullmatch(node) or state not in FLEET or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", service):
        raise ValueError("invalid fleet transition")
    title, severity = FLEET[state]
    return event(source=source, kind="fleet." + state, identity=(node, service, episode, at),
                 at=at, title=title, summary=node + " / " + service,
                 category="fleet", severity=severity, node=node)


def observe_inventory(snapshot, previous):
    """Pure diff of trusted snapshots; missing contact is not a confirmed outage."""
    current = {row["node"]: [row["reachable"], row["identity_verified"]]
               for row in snapshot["nodes"]}
    if previous is None:
        return current, []
    changes = []
    for node, (reach, verified) in sorted(current.items()):
        if node not in previous:
            changes.append((node, "enrolled"))
        elif reach == "reachable" and previous[node][0] != "reachable":
            changes.append((node, "contact_restored"))
        elif reach == "unknown" and previous[node][0] == "reachable":
            changes.append((node, "contact_unknown"))
        if node in previous and verified != previous[node][1]:
            changes.append((node, "identity_verified" if verified else "identity_unverified"))
    for node in sorted(set(previous) - set(current)):
        changes.append((node, "registration_removed"))
    return current, changes


def inventory_once(outbox, config, *, loader=None):
    """Queue trusted inventory diffs and checkpoint atomically, without network."""
    if loader is None:
        from .node_registry_inventory import load
        loader = load
    snapshot = loader()
    from .activity_feed import _utc, _canonical, FeedCapacityError
    from contextlib import closing
    stamp = _utc(snapshot["generated_at"])
    with closing(outbox._connect()) as db, outbox._write(db):
        outbox._check_binding(db)
        db.execute("CREATE TABLE IF NOT EXISTS inventory_feed_v2 (binding TEXT PRIMARY KEY, stamp TEXT NOT NULL, state TEXT NOT NULL)")
        if not outbox.binding:
            raise PermissionError("bound inventory outbox required")
        db.execute("DELETE FROM inventory_feed_v2 WHERE binding<>?", (outbox.binding,))
        old = db.execute("SELECT stamp,state FROM inventory_feed_v2 WHERE binding=?", (outbox.binding,)).fetchone()
        if old and stamp <= old[0]:
            return 0
        current, changes = observe_inventory(snapshot, json.loads(old[1]) if old else None)
        labels = {"enrolled": "Node enrolled", "contact_restored": "WireGuard contact observed",
                  "contact_unknown": "WireGuard contact no longer confirmed",
                  "identity_verified": "Node identity verified", "identity_unverified": "Node identity no longer verified",
                  "registration_removed": "Node absent from active registry"}
        if changes:
            from .activity_feed_quota import admit, OUTBOX_WAL
            admit(outbox.path, OUTBOX_WAL)
        for node, state in changes:
            value = event(source=config["source"], kind="fleet." + state, identity=(node, stamp),
                          at=stamp, title=labels[state], summary=node, category="fleet",
                          severity="warning" if state in ("contact_unknown","identity_unverified","registration_removed") else "info",
                          node=node)
            if db.execute("SELECT COUNT(*) FROM queue").fetchone()[0] >= outbox.capacity:
                db.execute("DELETE FROM queue WHERE seq IN (SELECT seq FROM queue WHERE state='delivered' ORDER BY seq LIMIT 1)")
                if db.execute("SELECT COUNT(*) FROM queue").fetchone()[0] >= outbox.capacity:
                    raise FeedCapacityError("inventory outbox full")
            now = int(outbox.clock())
            db.execute("INSERT INTO queue(source,event_id,payload,created,due) VALUES(?,?,?,?,?)",
                       (value["source"], value["id"], _canonical(value), now, now))
        db.execute("INSERT OR REPLACE INTO inventory_feed_v2 VALUES(?,?,?)", (outbox.binding, stamp, json.dumps(current)))
        return len(changes)
