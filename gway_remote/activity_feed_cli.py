"""Universal feed command: durable enqueue and separately invoked HTTPS drain."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
import uuid

from .activity_feed import _canonical, MAX_EVENT_BYTES, validate_event
from .activity_feed_http import parse_event, PATH
from .activity_feed_outbox import Outbox

CONFIG = Path.home() / ".config/gway-remote/feed.json"
STATE = Path.home() / ".local/state/gway-remote/feed"


def read_private(path, maximum):
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_nlink != 1 or info.st_size > maximum):
            raise PermissionError("unsafe feed configuration")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(maximum + 1)
        if len(raw) > maximum:
            raise ValueError("oversized configuration")
        return raw
    finally:
        os.close(fd)


def load_config(path=CONFIG):
    value = json.loads(read_private(path, 4096))
    if type(value) is not dict or set(value) != {"endpoint", "source", "node", "token_file", "principal"}:
        raise ValueError("invalid feed configuration")
    if type(value["principal"]) is not str or not re.fullmatch(r"[a-f0-9]{24}", value["principal"]):
        raise ValueError("stable publisher root principal required")
    endpoint = value["endpoint"]
    if type(endpoint) is not str or any(c.isspace() or c == chr(92) for c in endpoint):
        raise ValueError("invalid feed endpoint")
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.path != PATH or parsed.query or parsed.fragment
            or "?" in endpoint or "#" in endpoint):
        raise ValueError("feed requires pinned configured HTTPS endpoint")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("invalid endpoint port")
    if type(value["token_file"]) is not str or not Path(value["token_file"]).is_absolute():
        raise ValueError("absolute credential path required")
    # Validate source and default node without reaching network.
    example = {"specversion": "1.0", "id": "config", "source": value["source"], "type": "activity.recorded",
               "time": "2026-01-01T00:00:00Z", "data": {"title": "config", "summary": "config",
               "category": "general", "severity": "info"}}
    if value["node"] is not None:
        example["data"]["node"] = value["node"]
    validate_event(example)
    return value


def route_binding(config):
    return hashlib.sha256(json.dumps([config["endpoint"], config["source"], config["principal"]],
                                     separators=(",", ":")).encode()).hexdigest()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HTTPSPublisher:
    """Existing Watchtower TLS/bearer transport, no proxy or redirect fallback."""
    def __init__(self, config, *, opener=None):
        self.config = config
        self.opener = opener or build_opener(ProxyHandler({}), NoRedirect())

    def __call__(self, event):
        if event["source"] != self.config["source"]:
            return "dead"
        try:
            token = read_private(self.config["token_file"], 256).decode("ascii").strip()
            if not re.fullmatch(r"gwr_[a-f0-9]{24}_[A-Za-z0-9_-]{1,128}", token):
                return "retry"
            request = Request(self.config["endpoint"], data=_canonical(event).encode("ascii"),
                              headers={"Authorization": "Bearer " + token,
                                       "Content-Type": "application/cloudevents+json",
                                       "X-Gway-Feed-Principal": self.config["principal"]}, method="POST")
            with self.opener.open(request, timeout=4) as response:
                if response.status not in (200, 201):
                    return "retry"
                raw = response.read(MAX_EVENT_BYTES + 1025)
                if len(raw) > MAX_EVENT_BYTES + 1024:
                    return "retry"
                receipt = json.loads(raw)
                if (type(receipt) is dict and type(receipt.get("seq")) is int
                        and receipt["seq"] > 0 and receipt.get("event") == event
                        and type(receipt.get("received_at")) is str):
                    return "delivered"
                return "retry"
        except HTTPError as exc:
            code = exc.code
            exc.close()
            return "dead" if code in (400, 409, 413, 415, 422) else "retry"
        except (OSError, ValueError, URLError, RecursionError):
            return "retry"


def build_event(args, config):
    if args.json is not None:
        if args.title or any(getattr(args, x) is not None for x in
                             ("summary","type","category","severity","repo","node","id","time","url","commit","issue","pr")):
            raise ValueError("JSON is exclusive of structured options")
        if args.json == "-":
            raw = sys.stdin.buffer.read(MAX_EVENT_BYTES + 1)
        else:
            with open(args.json, "rb") as stream:
                raw = stream.read(MAX_EVENT_BYTES + 1)
        event = parse_event(raw)
    else:
        if not args.title:
            raise ValueError("event title required")
        data = {"title": args.title, "summary": args.summary or args.title,
                "category": args.category or "general", "severity": args.severity or "info"}
        for key, value in (("node", args.node if args.node is not None else config["node"]),
                           ("repository", args.repo), ("url", args.url), ("commit", args.commit),
                           ("issue", args.issue), ("pr", args.pr)):
            if value is not None:
                data[key] = value
        # Explicit id requires explicit time so producer retries are immutable.
        if args.id is not None and args.time is None:
            raise ValueError("--id requires stable --time")
        event = validate_event({"specversion": "1.0", "id": args.id or uuid.uuid4().hex,
                                "source": config["source"], "type": args.type or "activity.recorded",
                                "time": args.time or datetime.now(timezone.utc).isoformat(), "data": data})
    if event["source"] != config["source"]:
        raise PermissionError("source does not match installed configuration")
    return event


def main(argv=None, *, config_path=CONFIG, state_path=STATE):
    parser = argparse.ArgumentParser(prog="feed", description="Queue quiet activity events; flush separately.")
    parser.add_argument("title", nargs="?")
    parser.add_argument("--json", metavar="FILE")
    for opt in ("summary", "type", "category", "severity", "repo", "node", "id", "time", "url", "commit"):
        parser.add_argument("--" + opt)
    parser.add_argument("--issue", type=int)
    parser.add_argument("--pr", type=int)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--flush", action="store_true")
    modes.add_argument("--status", action="store_true")
    modes.add_argument("--check-config", action="store_true")
    modes.add_argument("--purge-dead", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.flush or args.status or args.purge_dead or args.check_config:
            if args.title or any(getattr(args, x) is not None for x in
                ("json","summary","type","category","severity","repo","node","id","time","url","commit","issue","pr")):
                raise ValueError("maintenance modes do not accept events")
        config = None if args.status or args.purge_dead else load_config(config_path)
        outbox = Outbox(state_path, binding=route_binding(config) if config else None)
        if args.check_config:
            token = read_private(config["token_file"], 256).decode("ascii").strip()
            if not re.fullmatch(r"gwr_[a-f0-9]{24}_[A-Za-z0-9_-]{1,128}", token):
                raise ValueError("invalid scoped credential format")
            result = {"configured": True}
        elif args.status:
            result = outbox.status()
        elif args.purge_dead:
            result = {"purged": outbox.purge_dead()}
        elif args.flush:
            # Watchtower-only opt-in under its existing authorized reader account.
            try:
                flag = Path(config_path).parent / "feed-inventory.enabled"
                if read_private(flag, 16).strip() == b"enabled":
                    from .activity_feed_hooks import inventory_once
                    inventory_once(outbox, config)
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                pass
            result = outbox.flush(HTTPSPublisher(config))
        else:
            event = build_event(args, config)
            result = {"id": event["id"], "state": outbox.enqueue(event)}
        print(json.dumps(result, sort_keys=True))
        return 1 if result.get("state") == "dead" else 0
    except (OSError, sqlite3.Error, ValueError, RuntimeError, RecursionError):
        print("feed: operation unavailable; event may not be queued", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
