"""Best-effort audio for authorized MCP node execution on the executing node.

Call only from the node-side bounded executor after admission. Never invoke
on Watchtower, for inventory reads, previews, or denied requests.
"""
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time

EVENTS = frozenset({"mcp-exec-started", "mcp-exec-completed",
                    "mcp-exec-failed", "mcp-exec-timed-out"})
SAFE_ID = re.compile(r"[a-zA-Z0-9_-]{1,96}\\Z")


class McpOperationSound:
    """Exactly one notification per (request, event), without command contents."""

    def __init__(self, node, request_id, *, database=None, run=None):
        if not isinstance(node, str) or not SAFE_ID.fullmatch(node):
            raise ValueError("invalid_node")
        if not isinstance(request_id, str) or not SAFE_ID.fullmatch(request_id):
            raise ValueError("invalid_request_id")
        self.node = node
        self.request_id = request_id
        self.database = Path(database) if database is not None else (
            Path.home() / ".local/state/gway-remote/mcp-sounds.sqlite3")
        self.run = run or subprocess.run

    def __call__(self, event):
        if event not in EVENTS or os.environ.get("GWAY_REMOTE_SOUND_DISABLE") == "1":
            return
        try:
            self.database.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.database, timeout=0.1) as db:
                db.execute("CREATE TABLE IF NOT EXISTS emitted "
                           "(request TEXT, node TEXT, event TEXT, at REAL, "
                           "PRIMARY KEY(request,node,event))")
                now = time.time()
                db.execute("DELETE FROM emitted WHERE at < ?", (now - 7 * 86400,))
                claimed = db.execute(
                    "INSERT OR IGNORE INTO emitted VALUES (?,?,?,?)",
                    (self.request_id, self.node, event, now)).rowcount
            if claimed:
                self.run([str(Path.home() / ".local/bin/sound"), "--event", event,
                          "--source", "gway-remote"], timeout=3, check=False,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            # Audio cannot affect execution, status, results, or retries.
            pass
