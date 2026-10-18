"""Conservative durable CI alert episodes for the local health watcher.

Only consecutive comparable completed workflow runs are used. PR and main
runs are separate lanes; unrelated workflow successes cannot clear alerts.
"""
import json
import sqlite3

BAD = {"failure", "timed_out", "action_required"}


def reconcile(connection, repositories, completed_at):
    connection.execute(
        "CREATE TABLE IF NOT EXISTS ci_episodes ("
        "id TEXT PRIMARY KEY, repository TEXT NOT NULL, lane TEXT NOT NULL, "
        "workflow TEXT NOT NULL, state TEXT NOT NULL, "
        "opened_at TEXT NOT NULL, resolved_at TEXT, "
        "resolution_kind TEXT, evidence_url TEXT)")
    connection.execute("CREATE TABLE IF NOT EXISTS ci_lane_cursor (lane_id TEXT PRIMARY KEY, latest_run_id INTEGER NOT NULL)")
    alerts = []
    for repo in repositories:
        name = repo["name"]
        for lane in repo.get("ci_lanes", []):
            workflow = lane["workflow"]
            trigger = lane["trigger"]
            branch = lane["branch"]
            identity = json.dumps([name, workflow, trigger, branch], separators=(",", ":"))
            runs = lane["completed_runs"]
            if not runs:
                continue
            latest = runs[0]
            previous = runs[1] if len(runs) > 1 else None
            cursor = connection.execute(
                "SELECT latest_run_id FROM ci_lane_cursor WHERE lane_id=?", (identity,)).fetchone()
            latest_id = int(latest["id"])
            fresh = cursor is None or latest_id > cursor[0]
            if fresh:
                connection.execute(
                    "INSERT INTO ci_lane_cursor VALUES (?, ?) "
                    "ON CONFLICT(lane_id) DO UPDATE SET latest_run_id=excluded.latest_run_id",
                    (identity, latest_id))
            current = connection.execute(
                "SELECT id, state, opened_at, resolved_at, resolution_kind, evidence_url "
                "FROM ci_episodes WHERE id=? AND state='ACTIVE'", (identity,)).fetchone()
            if current and fresh and latest["conclusion"] == "success":
                connection.execute(
                    "UPDATE ci_episodes SET state='RESOLVED', resolved_at=?, "
                    "resolution_kind='fixed', evidence_url=? WHERE id=?",
                    (completed_at, latest["url"], identity))
                alerts.append({
                    "id": identity, "repository": name, "state": "RESOLVED",
                    "category": "CI_ANOMALY", "title": workflow + " recovered",
                    "resolution_kind": "fixed", "evidence_url": latest["url"],
                    "next_action": "None"})
            elif current:
                alerts.append({
                    "id": identity, "repository": name, "state": "ACTIVE",
                    "category": "CI_ANOMALY", "title": workflow + " repeatedly failing",
                    "evidence_url": current[5],
                    "next_action": "Inspect failed workflow"})
            elif (fresh and previous is not None and latest["conclusion"] in BAD
                  and previous["conclusion"] in BAD):
                connection.execute(
                    "INSERT INTO ci_episodes "
                    "(id, repository, lane, workflow, state, opened_at, evidence_url) "
                    "VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET state='ACTIVE', opened_at=excluded.opened_at, "
                    "resolved_at=NULL, resolution_kind=NULL, evidence_url=excluded.evidence_url",
                    (identity, name, trigger + ":" + branch, workflow,
                     completed_at, latest["url"]))
                alerts.append({
                    "id": identity, "repository": name, "state": "ACTIVE",
                    "category": "CI_ANOMALY", "title": workflow + " repeatedly failing",
                    "evidence_url": latest["url"],
                    "next_action": "Inspect failed workflow"})
    return alerts
