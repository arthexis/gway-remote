"""Opt-in Watchtower Activity Feed HTTP adapter; no new credentials or listener."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qs, urlsplit

from .activity_feed import EventConflict, FeedCapacityError, MAX_EVENT_BYTES, validate_event
from .lcd_sound_grant_store import load_operator_grants

PATH = "/api/feed/events"
MAX_HTTP_PAGE = 50
MAX_RESPONSE = 1024 * 1024
GRANT_PATH = Path("/etc/gway-remote/activity-feed-sources.json")


def load_feed_grants():
    # Reuse the existing root-owned snapshot reader, not the LCD grants.
    return load_operator_grants(GRANT_PATH)


def is_feed_path(path):
    raw = path.split("?", 1)[0]
    return raw == PATH or raw.startswith(PATH + "/")


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("nonfinite JSON number")


def parse_event(raw):
    if not 0 < len(raw) <= MAX_EVENT_BYTES:
        raise ValueError("invalid request size")
    return validate_event(json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs,
                                     parse_constant=_invalid_constant))


def _allowed(value, values):
    return (type(values) is list and 0 < len(values) <= 64
            and all(v is None or (type(v) is str and 0 < len(v) <= 256) for v in values)
            and value in values)


def _public(record):
    # Credential registry identifiers are internal, not feed metadata.
    return {k: v for k, v in record.items() if k != "producer"}


def _number(value, maximum, minimum=0):
    if not re.fullmatch(r"[0-9]{1,19}", value):
        raise ValueError("invalid integer")
    result = int(value)
    if not minimum <= result <= maximum:
        raise ValueError("integer out of range")
    return result


class ActivityFeedAPI:
    """Readers: existing read or execute scope. Writers: narrow feed scope
    or existing execute scope, plus exact grant. Never distribute execute
    credentials to producers. Grants are reloaded for each publish.
    """
    def __init__(self, store, registry, load_grants):
        self.store, self.registry, self.load_grants = store, registry, load_grants

    def can_read(self, bearer):
        return (self.registry.verify(bearer, required_scope="gway:read")
                or self.registry.verify(bearer, required_scope="gway:execute"))

    def principal(self, bearer):
        if self.registry.verify(bearer, required_scope="gway:feed-publish"):
            return self.registry.feed_principal(bearer)
        return self.registry.execution_principal(bearer)

    def publish(self, principal, event):
        grants = self.load_grants()
        grant = grants.get(principal) if type(grants) is dict else None
        if (type(grant) is not dict or set(grant) != {"enabled", "source", "nodes", "repositories", "types"}
                or grant["enabled"] is not True or event["source"] != grant["source"]
                or not _allowed(event["data"].get("node"), grant["nodes"])
                or not _allowed(event["data"].get("repository"), grant["repositories"])
                or not _allowed(event["type"], grant["types"])):
            raise PermissionError("producer not authorized")
        record, inserted = self.store.append(event, producer=principal, allowed_source=grant["source"])
        return (201 if inserted else 200), _public(record)

    def read(self, path):
        if len(path) > 2048:
            raise ValueError("query too long")
        parsed = urlsplit(path)
        if parsed.fragment or parsed.netloc or parsed.scheme:
            raise ValueError("invalid request target")
        if parsed.path != PATH:
            if parsed.query or not re.fullmatch(re.escape(PATH) + r"/[0-9]{1,19}", parsed.path):
                raise ValueError("invalid event path")
            record = self.store.get(_number(parsed.path.rsplit("/", 1)[1], 2**63 - 1, 1))
            return (200, _public(record)) if record else (404, {"error": "not_found"})
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=4,
                         encoding="utf-8", errors="strict")
        if set(query) - {"after", "before", "limit", "category"} or any(len(v) != 1 for v in query.values()):
            raise ValueError("invalid query")
        if "after" in query and "before" in query:
            raise ValueError("ambiguous pagination")
        limit = _number(query.get("limit", ["30"])[0], MAX_HTTP_PAGE, 1)
        category = query.get("category", [None])[0]
        if "after" in query:
            result = self.store.list_after(_number(query["after"][0], 2**63 - 1), limit=limit, category=category)
        else:
            before = _number(query["before"][0], 2**63 - 1, 1) if "before" in query else None
            result = self.store.list_recent(before=before, limit=limit, category=category)
        result["items"] = [_public(item) for item in result["items"]]
        return 200, result


def _respond(handler, status, value):
    body = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")
    if len(body) > MAX_RESPONSE:
        status, body = 500, b'{"error":"response_too_large"}'
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Connection", "close")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.close_connection = True
    handler.wfile.write(body)


def handle(handler, method):
    api = handler.server.activity_feed
    # Close rather than reuse a connection on malformed or unread request bodies.
    handler.close_connection = True
    headers = handler.headers
    if headers.get("Origin") is not None:
        return _respond(handler, 403, {"error": "forbidden"})
    auth = headers.get_all("Authorization", [])
    if len(auth) != 1 or not auth[0].startswith("Bearer ") or len(auth[0]) > 256:
        return _respond(handler, 401, {"error": "unauthorized"})
    bearer = auth[0][7:]
    try:
        if method == "GET":
            if not api.can_read(bearer):
                return _respond(handler, 401, {"error": "unauthorized"})
            if headers.get("Transfer-Encoding") is not None or headers.get_all("Content-Length", []):
                return _respond(handler, 400, {"error": "invalid_request"})
            status, value = api.read(handler.path)
        else:
            if not (api.can_read(bearer) or api.registry.verify(bearer, required_scope="gway:feed-publish")):
                return _respond(handler, 401, {"error": "unauthorized"})
            principal = api.principal(bearer)
            binding = headers.get_all("X-Gway-Feed-Principal", [])
            if binding and (len(binding) != 1 or binding[0] != principal):
                return _respond(handler, 403, {"error": "forbidden"})
            if handler.path != PATH:
                return _respond(handler, 404, {"error": "not_found"})
            lengths = headers.get_all("Content-Length", [])
            content_types = headers.get_all("Content-Type", [])
            if (headers.get("Transfer-Encoding") is not None or len(lengths) != 1
                    or not re.fullmatch(r"[0-9]{1,10}", lengths[0])):
                return _respond(handler, 400, {"error": "invalid_request"})
            length = int(lengths[0])
            if not 0 < length <= MAX_EVENT_BYTES:
                return _respond(handler, 413, {"error": "request_too_large"})
            if len(content_types) != 1 or content_types[0].lower().strip() not in (
                    "application/json", "application/cloudevents+json"):
                return _respond(handler, 415, {"error": "unsupported_media_type"})
            handler.connection.settimeout(5)
            raw = handler.rfile.read(length)
            if len(raw) != length:
                raise ValueError("incomplete request")
            status, value = api.publish(principal, parse_event(raw))
    except PermissionError:
        status, value = 403, {"error": "forbidden"}
    except EventConflict:
        status, value = 409, {"error": "event_conflict"}
    except (ValueError, UnicodeError, RecursionError):
        status, value = 400, {"error": "invalid_request"}
    except (FeedCapacityError, sqlite3.Error, OSError, RuntimeError):
        status, value = 503, {"error": "feed_unavailable"}
    return _respond(handler, status, value)
