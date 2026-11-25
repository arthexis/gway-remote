"""Read-only mobile Feed route; delegate credential verification to existing mobile API.

Watchtower calls the fixed WireGuard health endpoint. No mobile credential is
stored or interpreted here, no MCP bearer is minted, and no write route exists.
"""
import http.client
import json
import re
import sqlite3
from .activity_feed_http import PATH, _respond

MOBILE_PATH = "/api/v1/feed/events"
MOBILE_API_HOST = "10.90.0.2"
MOBILE_API_PORT = 8765


def is_mobile_feed_path(path):
    return path.split("?", 1)[0] == MOBILE_PATH


def verify_mobile_key(authorization):
    # Direct connection: no redirect handler, proxy, caller-selected host or path.
    conn = http.client.HTTPConnection(MOBILE_API_HOST, MOBILE_API_PORT, timeout=3)
    try:
        conn.request("GET", "/api/v1/health", headers={"Authorization": authorization,
                    "Accept": "application/json", "Connection": "close"})
        response = conn.getresponse()
        if response.status in (401, 403):
            return False
        if response.status != 200 or not response.getheader("Content-Type", "").startswith("application/json"):
            raise RuntimeError("mobile authentication unavailable")
        raw = response.read(1025)
        if len(raw) > 1024 or json.loads(raw) != {"status": "ok", "api": "gway-remote/v1"}:
            raise RuntimeError("mobile authentication response invalid")
        return True
    finally:
        conn.close()


def handle_mobile_feed(handler):
    handler.close_connection = True
    headers = handler.headers
    if headers.get("Origin") is not None:
        return _respond(handler, 403, {"error": "forbidden"})
    auth = headers.get_all("Authorization", [])
    if len(auth) != 1 or not re.fullmatch(r"Bearer [!-~]{1,153}", auth[0]):
        return _respond(handler, 401, {"error": "unauthorized"})
    if headers.get("Transfer-Encoding") is not None or headers.get_all("Content-Length", []):
        return _respond(handler, 400, {"error": "invalid_request"})
    try:
        if not verify_mobile_key(auth[0]):
            return _respond(handler, 401, {"error": "unauthorized"})
    except (OSError, ValueError, RuntimeError, http.client.HTTPException):
        return _respond(handler, 503, {"error": "mobile_auth_unavailable"})
    api = getattr(handler.server, "activity_feed", None)
    if api is None:
        return _respond(handler, 404, {"error": "feed_not_enabled"})
    try:
        status, value = api.read(PATH + handler.path[len(MOBILE_PATH):])
    except (ValueError, UnicodeError, RecursionError):
        return _respond(handler, 400, {"error": "invalid_request"})
    except (OSError, RuntimeError, sqlite3.Error):
        return _respond(handler, 503, {"error": "feed_unavailable"})
    return _respond(handler, status, value)
