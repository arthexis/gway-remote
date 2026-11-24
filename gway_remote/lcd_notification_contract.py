"""Pure allowlist for gway-notification/v1 sent over authenticated LCD route.

Identity is bound at ingress to verified source grants. The receiver sees the
trusted Watchtower relay but never confuses it with the producer identity.
"""
from __future__ import annotations
import json
import re

SCHEMA = "gway-notification/v1"
NODE = re.compile(r"(?:gway-[0-9]{3,}|ocpp-abb-1|gelectriic\.com)\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]{1,64}/[A-Za-z0-9_.-]{1,100}\Z")
SERVICE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}\Z")
EPISODE = re.compile(r"[A-Za-z0-9:_-]{1,80}\Z")
REASON = re.compile(r"[A-Z][A-Z0-9_]{0,31}\Z")

STATES = {
    "agentops": {"finished": "important", "codex_failed": "error", "interrupted": "error"},
    "fleet": {"down": "critical", "unreachable": "error",
              "degraded": "error", "recovered": "important"},
    "deploy": {"deploy-started": "info", "deploy-activated": "info",
               "deploy-skipped": "important", "deploy-verified": "important",
               "deploy-failed": "error", "rollback-started": "important",
               "rollback-verified": "important", "rollback-failed": "critical"},
}


def validate_notice(doc):
    if (type(doc) is not dict or set(doc) != {
        "schema", "system", "origin_node", "target_node", "subject",
        "state", "severity", "reason_code", "episode_id", "expires_in"
    } or doc["schema"] != SCHEMA):
        raise ValueError("invalid notification schema")
    system = doc["system"]
    if type(system) is not str or system not in STATES:
        raise ValueError("invalid notification system")
    if (type(doc["state"]) is not str or doc["state"] not in STATES[system]
            or doc["severity"] != STATES[system][doc["state"]]):
        raise ValueError("inconsistent notification severity")
    if any(type(doc[key]) is not str or not NODE.fullmatch(doc[key])
           for key in ("origin_node", "target_node")):
        raise ValueError("invalid notification node")
    if (type(doc["episode_id"]) is not str or
            not EPISODE.fullmatch(doc["episode_id"])):
        raise ValueError("invalid notification episode")
    if (type(doc["reason_code"]) is not str or
            not REASON.fullmatch(doc["reason_code"])):
        raise ValueError("invalid reason code")
    if type(doc["expires_in"]) is not int or not 5 <= doc["expires_in"] <= 300:
        raise ValueError("invalid notification duration")
    subject = doc["subject"]
    if type(subject) is not dict:
        raise ValueError("invalid notification subject")
    if system == "agentops":
        if (set(subject) != {"type", "repository", "number"} or
                subject["type"] != "github_issue" or
                type(subject["repository"]) is not str or
                not REPO.fullmatch(subject["repository"]) or
                type(subject["number"]) is not int or
                not 1 <= subject["number"] <= 999999999):
            raise ValueError("invalid issue")
    elif system == "deploy":
        if (set(subject) != {"type", "repository"} or
                subject["type"] != "repository" or
                type(subject["repository"]) is not str or
                not REPO.fullmatch(subject["repository"])):
            raise ValueError("invalid repository")
    else:
        if (set(subject) != {"type", "name"} or
                subject["type"] != "service" or
                type(subject["name"]) is not str or
                not SERVICE.fullmatch(subject["name"])):
            raise ValueError("invalid service")
    if len(json.dumps(doc,sort_keys=True,separators=(",", ":")).encode()) > 4096:
        raise ValueError("oversized notification")
    return doc
