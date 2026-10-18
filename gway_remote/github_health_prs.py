"""Durable PR check episodes, requiring verified branch-protection evidence.

A missing PR is not called fixed: it is closed with unresolved disposition.
A new head SHA starts a new candidate; no repeated RESOLVED notification.
"""
import json
from datetime import datetime


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def reconcile_prs(connection, repositories, completed_at):
    connection.execute(
        "CREATE TABLE IF NOT EXISTS pr_blockers ("
        "repository TEXT NOT NULL, number INTEGER NOT NULL, head_sha TEXT NOT NULL, "
        "first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, "
        "PRIMARY KEY(repository, number))")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS pr_episodes ("
        "id TEXT PRIMARY KEY, repository TEXT NOT NULL, number INTEGER NOT NULL, "
        "head_sha TEXT NOT NULL, state TEXT NOT NULL, opened_at TEXT NOT NULL, "
        "resolved_at TEXT, resolution_kind TEXT, evidence_url TEXT)")
    alerts = []
    now = parse_time(completed_at)
    for repo in repositories:
        name = repo["name"]
        observed = set()
        for pr in repo.get("pr_evidence", []):
            number = pr["number"]
            sha = pr["head_sha"]
            observed.add(number)
            candidate = (not pr["draft"] and not pr["on_hold"]
                         and pr["head_check"] == "failure"
                         and pr["required_check_verified"])
            existing = connection.execute(
                "SELECT head_sha, first_seen FROM pr_blockers "
                "WHERE repository=? AND number=?", (name, number)).fetchone()
            active = connection.execute(
                "SELECT id, head_sha, evidence_url FROM pr_episodes "
                "WHERE repository=? AND number=? AND state='ACTIVE'",
                (name, number)).fetchone()
            if active and (not candidate or active[1] != sha):
                kind = "superseded" if active[1] != sha else "no_longer_blocked"
                connection.execute(
                    "UPDATE pr_episodes SET state='RESOLVED', resolved_at=?, resolution_kind=? "
                    "WHERE id=?", (completed_at, kind, active[0]))
                alerts.append({"id": active[0], "repository": name, "state": "RESOLVED",
                               "category": "CI_FAILURE_STUCK",
                               "title": "PR #" + str(number) + " no longer blocked",
                               "resolution_kind": kind, "evidence_url": pr["url"],
                               "next_action": "Verify PR outcome"})
            if not candidate:
                connection.execute("DELETE FROM pr_blockers WHERE repository=? AND number=?",
                                   (name, number))
                continue
            if not existing or existing[0] != sha:
                connection.execute(
                    "INSERT OR REPLACE INTO pr_blockers VALUES (?, ?, ?, ?, ?)",
                    (name, number, sha, completed_at, completed_at))
                continue
            connection.execute(
                "UPDATE pr_blockers SET last_seen=? WHERE repository=? AND number=?",
                (completed_at, name, number))
            if (now - parse_time(existing[1])).total_seconds() < 3600:
                continue
            identity = json.dumps(["pr", name, number, sha], separators=(",", ":"))
            was_active = bool(active and active[0] == identity)
            if not was_active:
                connection.execute(
                    "INSERT INTO pr_episodes "
                    "(id, repository, number, head_sha, state, opened_at, evidence_url) "
                    "VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?) "
                    "ON CONFLICT(id) DO NOTHING",
                    (identity, name, number, sha, completed_at, pr["url"]))
                # Do not reopen a resolved episode for the same head.
                state = connection.execute(
                    "SELECT state FROM pr_episodes WHERE id=?", (identity,)).fetchone()[0]
                if state != "ACTIVE":
                    continue
            alerts.append({"id": identity, "repository": name, "state": "ACTIVE",
                           "category": "CI_FAILURE_STUCK",
                           "title": "PR #" + str(number) + " has persistent failing required checks",
                           "evidence_url": pr["url"],
                           "next_action": "Inspect required checks and automation",
                           "blocker_since": existing[1]})
        # Missing from the complete open-PR enumeration is not proof of a fix.
        stale = connection.execute(
            "SELECT id, number, evidence_url FROM pr_episodes "
            "WHERE repository=? AND state='ACTIVE'", (name,)).fetchall()
        for identity, number, url in stale:
            if number in observed:
                continue
            connection.execute(
                "UPDATE pr_episodes SET state='RESOLVED', resolved_at=?, "
                "resolution_kind='closed_without_verified_fix' WHERE id=?",
                (completed_at, identity))
            connection.execute(
                "DELETE FROM pr_blockers WHERE repository=? AND number=?", (name, number))
            alerts.append({"id": identity, "repository": name, "state": "RESOLVED",
                           "category": "CI_FAILURE_STUCK", "title": "PR #" + str(number) + " closed",
                           "resolution_kind": "closed_without_verified_fix",
                           "evidence_url": url, "next_action": "Review closure outcome"})
    return alerts
