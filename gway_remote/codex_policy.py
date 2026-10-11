"""Conservative local-only admission policy; no task execution or GitHub trust."""
from __future__ import annotations

import re

ALLOWED = {
    "arthexis/gway-remote": frozenset(("field-validation", "read-only-inspection")),
    "arthexis/ocpp-csms": frozenset(("field-validation", "read-only-inspection")),
    "arthexis/gway-lcd-sound": frozenset(("field-validation", "read-only-inspection")),
    "arthexis/gway-ap-kiosk": frozenset(("field-validation", "read-only-inspection")),
}
DEFAULT_PRIORITY = "P2"
PRIORITIES = ("P0", "P1", "P2", "P3")
ISSUE_MAX = 2147483647


def validate_request(kind: str, repository: str, issue: int, priority: str = DEFAULT_PRIORITY):
    if repository not in ALLOWED or kind not in ALLOWED[repository]:
        raise ValueError("repository or task kind is not allowed")
    if type(issue) is not int or not 1 <= issue <= ISSUE_MAX:
        raise ValueError("issue must be a positive GitHub issue number")
    if priority not in PRIORITIES:
        raise ValueError("priority must be P0, P1, P2 or P3")
    return {"kind": kind, "repository": repository, "issue": issue, "priority": priority}

# GitHub issue discovery must verify the immutable numeric account ID as well
# as the login, which may be renamed or reused.
TRUSTED_CREATOR_LOGIN = "arthexis"
TRUSTED_CREATOR_ID = None  # Must be pinned from GitHub before discovery is enabled.


def verify_issue_creator(issue: dict, *, trusted_id: int, trusted_login: str = TRUSTED_CREATOR_LOGIN) -> bool:
    """Fail closed unless GitHub's authoritative issue author matches both fields."""
    if type(trusted_id) is not int or trusted_id <= 0:
        return False
    if not isinstance(issue, dict) or "pull_request" in issue:
        return False
    author = issue.get("user")
    return (
        isinstance(author, dict)
        and type(author.get("id")) is int
        and author["id"] == trusted_id
        and isinstance(author.get("login"), str)
        and author["login"].casefold() == trusted_login.casefold()
    )
