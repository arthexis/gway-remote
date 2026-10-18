"""Persistent CI pending-run anomalies; compare only observed same run."""
import json
from datetime import datetime

def reconcile_pending(connection, repositories, completed_at):
    connection.execute(
        "CREATE TABLE IF NOT EXISTS pending_ci_alerts ("
        "id TEXT PRIMARY KEY, repository TEXT NOT NULL, state TEXT NOT NULL, "
        "category TEXT NOT NULL, first_seen TEXT NOT NULL, resolved_at TEXT, "
        "evidence_url TEXT)")
    now = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    alerts = []
    for repo in repositories:
        name = repo["name"]
        seen = set()
        completed_ids = set(repo.get('completed_run_ids', []))
        for run in repo.get("pending_runs", []):
            if not run.get("created_at"):
                continue
            try:
                age = (now - datetime.fromisoformat(
                    run["created_at"].replace("Z", "+00:00"))).total_seconds()
            except ValueError:
                continue
            category = ("STALE_IN_PROGRESS" if run["status"] == "in_progress"
                        else "CI_ABNORMALLY_LONG")
            if age < 7200:
                continue
            identity = json.dumps(["pending-ci", name, run["id"]], separators=(",", ":"))
            seen.add(identity)
            row = connection.execute(
                "SELECT state FROM pending_ci_alerts WHERE id=?", (identity,)).fetchone()
            if row and row[0] == "RESOLVED":
                continue
            if row is None:
                connection.execute(
                    "INSERT INTO pending_ci_alerts VALUES (?, ?, 'ACTIVE', ?, ?, NULL, ?)",
                    (identity, name, category, completed_at, run["url"]))
            alerts.append({"id": identity, "repository": name, "state": "ACTIVE",
                           "category": category,
                           "title": run.get("name", "Workflow") + " exceeds two hours",
                           "evidence_url": run["url"],
                           "next_action": "Inspect outstanding GitHub workflow"})
        current = connection.execute(
            "SELECT id, category, evidence_url FROM pending_ci_alerts "
            "WHERE repository=? AND state='ACTIVE'", (name,)).fetchall()
        for identity, category, url in current:
            if identity in seen:
                continue
            # Bounded-list disappearance is not completion evidence.
            try:
                run_id = json.loads(identity)[2]
            except (ValueError, IndexError, TypeError):
                continue
            if run_id not in completed_ids:
                alerts.append({"id": identity, "repository": name, "state": "ACTIVE",
                               "category": category, "title": "Workflow status unverified",
                               "evidence_url": url,
                               "next_action": "Verify workflow conclusion"})
                continue
            connection.execute(
                "UPDATE pending_ci_alerts SET state='RESOLVED', resolved_at=? WHERE id=?",
                (completed_at, identity))
            alerts.append({"id": identity, "repository": name, "state": "RESOLVED",
                           "category": category, "title": "Workflow no longer outstanding",
                           "resolution_kind": "completed_unverified_outcome",
                           "evidence_url": url, "next_action": "Verify workflow conclusion"})
    return alerts
