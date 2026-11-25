"""Watchtower-local feed tools and JSON Feed projection."""
from __future__ import annotations

from collections import Counter
import json
import sqlite3

from .activity_feed import EventConflict, FeedCapacityError, validate_event
from .activity_feed_http import _public

MAX_MCP_PAGE = 10
MAX_SUMMARY = 500
_CURSOR = {"type": "integer", "minimum": 0, "maximum": 2**63 - 1}
_PAGE = {"after": _CURSOR, "before": {**_CURSOR, "minimum": 1},
         "limit": {"type": "integer", "minimum": 1, "maximum": MAX_MCP_PAGE},
         "category": {"type": "string", "maxLength": 256}}


def _tool(name, description, properties, required=(), read=True):
    return {"name": "feed__" + name, "description": description,
            "annotations": {"readOnlyHint": read, "destructiveHint": False,
                            "idempotentHint": True},
            "inputSchema": {"type": "object", "properties": properties,
                            "required": list(required), "additionalProperties": False}}


FEED_TOOLS = (
    _tool("list", "List recent or incremental Activity Feed receipts; bounded cursor paging.", _PAGE),
    _tool("get", "Read one Activity Feed receipt by server sequence.",
          {"seq": {**_CURSOR, "minimum": 1}}, ("seq",)),
    _tool("summary", "Count categories and severities across up to 500 retained receipts after a cursor; continue if has_more.",
          {"after": _CURSOR, "limit": {"type": "integer", "minimum": 1, "maximum": MAX_SUMMARY}}),
    _tool("publish", "Publish a validated CloudEvent; requires execute and an explicit producer grant. No LCD/Sound alert.",
          {"event": {"type": "object", "required": ["specversion", "id", "source", "type", "time", "data"],
                     "properties": {"specversion": {"type": "string", "enum": ["1.0"]},
                                    "id": {"type": "string"}, "source": {"type": "string"},
                                    "type": {"type": "string"}, "time": {"type": "string"},
                                    "subject": {"type": "string"}, "data": {"type": "object"}},
                     "additionalProperties": False}}, ("event",), read=False),
)
FEED_NAMES = frozenset(t["name"] for t in FEED_TOOLS)


def _int(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("invalid integer")
    return value


def _page(store, args):
    if set(args) - set(_PAGE) or ("after" in args and "before" in args):
        raise ValueError("invalid pagination")
    limit = _int(args.get("limit", MAX_MCP_PAGE), 1, MAX_MCP_PAGE)
    if "category" in args and type(args["category"]) is not str:
        raise ValueError("invalid category")
    category = args.get("category")
    if "after" in args:
        result = store.list_after(_int(args["after"], 0, 2**63 - 1), limit=limit, category=category)
    else:
        before = _int(args["before"], 1, 2**63 - 1) if "before" in args else None
        result = store.list_recent(before=before, limit=limit, category=category)
    result["items"] = [_public(x) for x in result["items"]]
    return result


def _summary(store, args):
    if set(args) - {"after", "limit"}:
        raise ValueError("invalid summary arguments")
    cursor = _int(args.get("after", 0), 0, 2**63 - 1)
    limit = _int(args.get("limit", MAX_SUMMARY), 1, MAX_SUMMARY)
    category, severity = Counter(), Counter()
    total = 0
    while total < limit:
        page = store.list_after(cursor, limit=min(100, limit-total))
        for item in page["items"]:
            data = item["event"]["data"]
            category[data["category"]] += 1
            severity[data["severity"]] += 1
        total += len(page["items"])
        cursor = page["next_cursor"]
        if not page["has_more"]:
            break
    return {"count": total, "categories": dict(category), "severities": dict(severity),
            "next_cursor": cursor, "has_more": page["has_more"]}


def call_feed(api, name, args, bearer):
    try:
        if name not in FEED_NAMES or type(args) is not dict:
            raise ValueError("invalid tool arguments")
        if name == "feed__publish":
            principal = api.registry.execution_principal(bearer)
            if set(args) != {"event"}:
                raise ValueError("event required")
            status, receipt = api.publish(principal, validate_event(args["event"]))
            value = {"inserted": status == 201, "receipt": receipt}
        else:
            if not api.can_read(bearer):
                raise PermissionError("read required")
            if name == "feed__list":
                value = _page(api.store, args)
            elif name == "feed__summary":
                value = _summary(api.store, args)
            else:
                if set(args) != {"seq"}:
                    raise ValueError("sequence required")
                record = api.store.get(_int(args["seq"], 1, 2**63 - 1))
                value = _public(record) if record else {"error": "not_found"}
        error = "error" in value
    except PermissionError:
        value, error = {"error": "forbidden"}, True
    except EventConflict:
        value, error = {"error": "event_conflict"}, True
    except (ValueError, TypeError, RecursionError):
        value, error = {"error": "invalid_arguments"}, True
    except (FeedCapacityError, sqlite3.Error, OSError, RuntimeError):
        value, error = {"error": "feed_unavailable"}, True
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, separators=(",", ":"))}],
            "isError": error}


def json_feed(page):
    """JSON Feed 1.1; plain text only, stable receipt ID within this store."""
    items = []
    for row in page["items"]:
        event = row["event"]
        data = event["data"]
        item = {"id": str(row["seq"]), "title": data["title"], "content_text": data["summary"],
                "date_published": event["time"], "tags": [data["category"], data["severity"]],
                "_gway": {"sequence": row["seq"], "received_at": row["received_at"],
                          "type": event["type"], "source": event["source"]}}
        if "url" in data:
            item["url"] = data["url"]
        items.append(item)
    return {"version": "https://jsonfeed.org/version/1.1", "title": "GWay Activity Feed",
            "items": items, "_gway": {"next_cursor": page["next_cursor"], "has_more": page["has_more"]}}
