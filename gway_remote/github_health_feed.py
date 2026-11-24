"""Quiet CI episode transitions, after SQLite commit; no branch/log data."""
from .activity_feed_hooks import event, publish
from .github_health import REPOSITORIES


def publish_transitions(rows, completed_at, *, sink=publish):
    for identity, repo, opened, resolved, resolution in rows:
        if repo not in REPOSITORIES:
            continue
        if resolved == completed_at:
            state = "recovered" if resolution == "fixed" else "retired"
            title = "CI episode recovered" if state == "recovered" else "CI episode retired"
            severity = "success" if state == "recovered" else "info"
        elif opened == completed_at:
            state, title, severity = "opened", "Repeated CI failure", "warning"
        else:
            continue
        sink(lambda source: event(source=source, kind="github.ci_" + state,
             identity=(identity, opened), at=completed_at, title=title, summary=repo,
             category="github", severity=severity, repository=repo))
