"""Conservative PR blocker observations with a one-hour persistence gate.

Only explicit, repeated evidence of a failed head check is actionable.
Drafts, on-hold PRs, and nonterminal checks are never classified as stuck.
"""
import json
from datetime import datetime, timezone


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def reconcile_prs(connection, repositories, completed_at):
    connection.execute(
        "CREATE TABLE IF NOT EXISTS pr_blockers ("
        "repository TEXT NOT NULL, number INTEGER NOT NULL, head_sha TEXT NOT NULL, "
        "first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, "
        "PRIMARY KEY(repository, number))")
    alerts = []
    now = parse_time(completed_at)
    for repo in repositories:
        name = repo["name"]
        observed = set()
        for pr in repo.get("pr_evidence", []):
            number = pr["number"]
            observed.add(number)
            # A failing completed check is a candidate, not automatically stuck.
            candidate = (not pr["draft"] and not pr["on_hold"]
                         and pr["head_check"] == "failure")
            existing = connection.execute(
                "SELECT head_sha, first_seen FROM pr_blockers "
                "WHERE repository=? AND number=?", (name, number)).fetchone()
            if not candidate:
                connection.execute("DELETE FROM pr_blockers WHERE repository=? AND number=?",
                                   (name, number))
                continue
            if not existing or existing[0] != pr["head_sha"]:
                connection.execute(
                    "INSERT OR REPLACE INTO pr_blockers VALUES (?, ?, ?, ?, ?)",
                    (name, number, pr["head_sha"], completed_at, completed_at))
                continue
            connection.execute(
                "UPDATE pr_blockers SET last_seen=? WHERE repository=? AND number=?",
                (completed_at, name, number))
            if (now - parse_time(existing[1])).total_seconds() < 3600:
                continue
            alerts.append({
                "id": json.dumps(["pr", name, number, pr["head_sha"]]),
                "repository": name, "state": "ACTIVE",
                "category": "CI_FAILURE_STUCK",
                "title": "PR #" + str(number) + " has a persistent failing head check",
                "evidence_url": pr["url"],
                "next_action": "Inspect required checks and expected automation",
                "blocker_since": existing[1]})
        # Closed PRs must not be called fixed: absence is not a clearance.
        # Keep their historical rows for explicit future disposition checks.
    return alerts
