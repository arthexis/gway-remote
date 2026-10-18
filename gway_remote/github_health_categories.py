"""Evidence-gated PR blocker categories with durable transition episodes.

Never infer an approval or branch-protection requirement from a missing API
response. A closed PR is not proof that a blocker was fixed.
"""
import json
from datetime import datetime

CATEGORIES = ("REVIEW_BLOCKED", "BRANCH_FRESHNESS_BLOCKED",
              "READY_BUT_NOT_MERGING", "CI_MISSING",
              "AUTOMATION_STATE_INCONSISTENCY")
PERSISTENCE_SECONDS = 3600


def _time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def signals(pr):
    if pr.get("draft") or pr.get("on_hold"):
        return {}
    result = {}
    if pr.get("review_blocked") is True:
        result["REVIEW_BLOCKED"] = "A reviewer has outstanding requested changes"
    if pr.get("mergeable_state") == "dirty":
        result["BRANCH_FRESHNESS_BLOCKED"] = "Merge conflict prevents integration"
    if pr.get("mergeable_state") == "behind":
        result["BRANCH_FRESHNESS_BLOCKED"] = "Branch must be updated before merging"
    if pr.get("missing_required_checks"):
        result["CI_MISSING"] = "Required check has no matching head check-run"
    if (pr.get("auto_merge_enabled") and pr.get("mergeable_state") == "clean"
            and not pr.get("checks_pending") and not pr.get("checks_failing")
            and pr.get("age_seconds") is not None and pr["age_seconds"] >= 3600):
        result["READY_BUT_NOT_MERGING"] = "Auto-merge remains pending on a clean, quiet PR"
    if (pr.get("auto_merge_enabled") and pr.get("mergeable_state") == "blocked"
            and not pr.get("review_blocked") and not pr.get("checks_pending")
            and not pr.get("checks_failing") and pr.get("required_check_count", 0) > 0
            and not pr.get("missing_required_checks")):
        result["AUTOMATION_STATE_INCONSISTENCY"] = "Auto-merge blocked without a captured cause"
    return result


def reconcile_extra(connection, repositories, completed_at):
    connection.execute(
        "CREATE TABLE IF NOT EXISTS github_pr_candidates ("
        "id TEXT PRIMARY KEY, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL)")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS github_pr_alerts ("
        "id TEXT PRIMARY KEY, repository TEXT NOT NULL, number INTEGER NOT NULL, "
        "head_sha TEXT NOT NULL, category TEXT NOT NULL, state TEXT NOT NULL, "
        "opened_at TEXT NOT NULL, resolved_at TEXT, resolution_kind TEXT, "
        "evidence_url TEXT NOT NULL)")
    now = _time(completed_at)
    alerts = []
    for repo in repositories:
        name = repo["name"]
        active_ids = set()
        open_numbers = set()
        for pr in repo.get("pr_evidence", []):
            number = pr["number"]
            sha = pr["head_sha"]
            open_numbers.add(number)
            for category, reason in signals(pr).items():
                identity = json.dumps(["pr-category", name, number, sha, category],
                                      separators=(",", ":"))
                active_ids.add(identity)
                candidate = connection.execute(
                    "SELECT first_seen FROM github_pr_candidates WHERE id=?",
                    (identity,)).fetchone()
                if candidate is None:
                    connection.execute("INSERT INTO github_pr_candidates VALUES (?, ?, ?)",
                                       (identity, completed_at, completed_at))
                    continue
                connection.execute("UPDATE github_pr_candidates SET last_seen=? WHERE id=?",
                                   (completed_at, identity))
                if (now - _time(candidate[0])).total_seconds() < PERSISTENCE_SECONDS:
                    continue
                stored = connection.execute(
                    "SELECT state FROM github_pr_alerts WHERE id=?", (identity,)).fetchone()
                if stored and stored[0] == "RESOLVED":
                    continue
                if stored is None:
                    connection.execute(
                        "INSERT INTO github_pr_alerts "
                        "(id, repository, number, head_sha, category, state, opened_at, evidence_url) "
                        "VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, ?)",
                        (identity, name, number, sha, category, completed_at, pr["url"]))
                alerts.append({"id": identity, "repository": name, "state": "ACTIVE",
                               "category": category, "title": "PR #" + str(number) + ": " + category,
                               "evidence_url": pr["url"], "next_action": reason})
        rows = connection.execute(
            "SELECT id, number, head_sha, category, evidence_url FROM github_pr_alerts "
            "WHERE repository=? AND state='ACTIVE'", (name,)).fetchall()
        by_number = {p["number"]: p for p in repo.get("pr_evidence", [])}
        for identity, number, sha, category, url in rows:
            if identity in active_ids:
                continue
            if number not in open_numbers:
                kind = "closed_without_verified_fix"
            elif by_number[number]["head_sha"] != sha:
                kind = "superseded"
            elif by_number[number].get("draft") or by_number[number].get("on_hold"):
                kind = "cancelled"
            else:
                kind = "no_longer_blocked"
            connection.execute(
                "UPDATE github_pr_alerts SET state='RESOLVED', resolved_at=?, "
                "resolution_kind=? WHERE id=?", (completed_at, kind, identity))
            alerts.append({"id": identity, "repository": name, "state": "RESOLVED",
                           "category": category, "title": "PR #" + str(number) + " status changed",
                           "resolution_kind": kind, "evidence_url": url,
                           "next_action": "Review PR outcome"})
        # Drop stale candidates when evidence clears; a recurrence must persist anew.
        candidates = connection.execute(
            "SELECT id FROM github_pr_candidates WHERE id LIKE ?",
            ('%"' + name + '"%',)).fetchall()
        for (identity,) in candidates:
            if identity not in active_ids:
                connection.execute("DELETE FROM github_pr_candidates WHERE id=?", (identity,))
    return alerts
