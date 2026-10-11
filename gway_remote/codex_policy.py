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
