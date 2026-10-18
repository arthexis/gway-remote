"""Read-only inventory of configured appliance deployment targets."""
from datetime import datetime, timezone
from .attempts import read_attempts
from .github_state import GitHub, main_head
from .reconcile import TARGETS
from .status import installed_revision


def inventory(repository=None, *, client=None, attempts=None, installed=None):
    """Report attempt evidence separately from independently verified installation."""
    names = dict(TARGETS)
    if repository is not None and repository not in names:
        raise ValueError(f"Unknown repository: {repository}")
    client = client if client is not None else GitHub()
    attempts = attempts if attempts is not None else read_attempts()
    installed = installed if installed is not None else installed_revision
    rows = []
    for name, source in TARGETS:
        if repository is not None and repository != name:
            continue
        record = attempts.get(name) or {}
        verified = installed(name)
        latest = main_head(client, source)
        # Release symlinks may expose only 12 characters, unlike GitHub's full SHA.
        relation = ("unknown" if not verified else
                    "current" if latest.lower().startswith(verified.lower()) else "behind")
        rows.append({"name": name, "repository": source,
                     "attempted_at": record.get("at"),
                     "attempted_sha": record.get("sha"),
                     "attempt_status": record.get("status", "never-attempted"),
                     "installed_sha": verified,
                     "latest_sha": latest,
                     "revision_status": relation})
    return {"checked_at": datetime.now(timezone.utc).isoformat(),
            "components": rows}


def format_inventory(report):
    lines = [f'{"Component":<20} {"Last attempt (UTC)":<26} {"Attempt":<12} {"Installed":<13} {"Main":<13} Status']
    for row in report["components"]:
        timestamp = row["attempted_at"] or "—"
        lines.append(
            f'{row["name"]:<20} {timestamp[:25]:<26} '
            f'{row["attempt_status"]:<12} '
            f'{(row["installed_sha"] or "unknown")[:12]:<13} '
            f'{row["latest_sha"][:12]:<13} {row["revision_status"]}'
        )
    lines.append("Installed revision is verified independently; latest attempt is not proof of installation.")
    return "\n".join(lines)
