"""Durable, execution-disabled single-slot Codex task ledger.

Queue writes are local trusted API operations; no GitHub issue or external
payload can enqueue work until admission policy is implemented in Part B.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

STATES = ("requested", "queued", "running", "succeeded", "failed", "cancelled", "interrupted", "vetoed")
TERMINAL = frozenset(("succeeded", "failed", "cancelled", "interrupted", "vetoed"))
TRANSITIONS = {
    "requested": frozenset(("queued", "cancelled", "vetoed")),
    "queued": frozenset(("running", "cancelled", "vetoed")),
    "running": frozenset(("succeeded", "failed", "cancelled", "interrupted")),
    "vetoed": frozenset(("requested",)),
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
 id TEXT PRIMARY KEY,
 kind TEXT NOT NULL,
 repository TEXT NOT NULL,
 issue INTEGER NOT NULL CHECK(issue > 0),
 state TEXT NOT NULL CHECK(state IN ('requested','queued','running','succeeded','failed','cancelled','interrupted','vetoed')),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 detail TEXT NOT NULL DEFAULT '',
 priority TEXT NOT NULL DEFAULT 'P2'
);
CREATE UNIQUE INDEX IF NOT EXISTS single_running_task
 ON tasks(state) WHERE state = 'running';
CREATE UNIQUE INDEX IF NOT EXISTS active_task_identity ON tasks(repository,issue,kind) WHERE state IN ('requested','queued','running');
CREATE INDEX IF NOT EXISTS task_order ON tasks(state, created_at, id);
"""


def default_db() -> Path:
    return Path.home() / ".local/state/gway-remote/codex-tasks.sqlite3"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskQueue:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=10000")
        if self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'").fetchone():
            cols = {row[1] for row in self.db.execute("PRAGMA table_info(tasks)")}
            if "priority" not in cols:
                self.db.execute("ALTER TABLE tasks ADD COLUMN priority TEXT NOT NULL DEFAULT 'P2'")
        # SQLite CHECK constraints require rebuilding old tables to add vetoed.
        if self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'").fetchone():
            ddl = self.db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='tasks'").fetchone()[0]
            if "'vetoed'" not in ddl:
                self.db.execute("BEGIN IMMEDIATE")
                try:
                    self.db.execute("ALTER TABLE tasks RENAME TO tasks_previous")
                    self.db.execute("""CREATE TABLE tasks (
                        id TEXT PRIMARY KEY, kind TEXT NOT NULL, repository TEXT NOT NULL,
                        issue INTEGER NOT NULL CHECK(issue > 0),
                        state TEXT NOT NULL CHECK(state IN
                        ('requested','queued','running','succeeded','failed','cancelled','interrupted','vetoed')),
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                        detail TEXT NOT NULL DEFAULT '', priority TEXT NOT NULL DEFAULT 'P2')""")
                    self.db.execute("INSERT INTO tasks SELECT id,kind,repository,issue,state,created_at,updated_at,detail,priority FROM tasks_previous")
                    self.db.execute("DROP TABLE tasks_previous")
                    self.db.execute("COMMIT")
                except Exception:
                    self.db.execute("ROLLBACK")
                    raise
        self.db.executescript(SCHEMA)
        if self.path != Path(":memory:"):
            self.path.chmod(0o600)

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def get(self, task_id: str):
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None

    def list(self, limit: int = 50):
        if not 1 <= limit <= 500:
            raise ValueError("limit must be 1..500")
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC, id DESC LIMIT ?", (limit,))]

    def request(self, kind: str, repository: str, issue: int):
        if not kind or not repository or not isinstance(issue, int) or issue <= 0:
            raise ValueError("task metadata is required")
        task_id = str(uuid4())
        timestamp = now()
        self.db.execute("INSERT INTO tasks (id,kind,repository,issue,state,created_at,updated_at)"
                        " VALUES (?,?,?,?,'requested',?,?)",
                        (task_id, kind, repository, issue, timestamp, timestamp))
        return self.get(task_id)

    def admit(self, kind: str, repository: str, issue: int, priority: str = "P2"):
        """Local operator admission only; no external issue content is trusted."""
        from .codex_policy import validate_request
        data = validate_request(kind, repository, issue, priority)
        task_id, timestamp = str(uuid4()), now()
        try:
            self.db.execute(
                "INSERT INTO tasks (id,kind,repository,issue,priority,state,created_at,updated_at)"
                " VALUES (?,?,?,?,?,'requested',?,?)",
                (task_id, data["kind"], data["repository"], data["issue"],
                 data["priority"], timestamp, timestamp))
        except sqlite3.IntegrityError as exc:
            raise ValueError("an active request already exists for this issue and task kind") from exc
        return self.get(task_id)

    def transition(self, task_id: str, expected: str, target: str, detail: str = ""):
        if target not in TRANSITIONS.get(expected, ()):
            raise ValueError(f"invalid transition: {expected} -> {target}")
        if target == "running":
            # Part A deliberately has no executor; only an internal test hook
            # should use this transition until Part B/C add authorization.
            pass
        try:
            result = self.db.execute(
                "UPDATE tasks SET state=?, updated_at=?, detail=? WHERE id=? AND state=?",
                (target, now(), detail[:2000], task_id, expected))
        except sqlite3.IntegrityError as exc:
            raise ValueError("another task is already running") from exc
        if result.rowcount != 1:
            raise ValueError("task not found or state changed")
        return self.get(task_id)

    def veto(self, task_id: str, reason: str):
        if not reason.strip():
            raise ValueError("veto requires a reason")
        task = self.get(task_id)
        if not task or task["state"] not in ("requested", "queued"):
            raise ValueError("only requested or queued tasks may be vetoed")
        return self.transition(task_id, task["state"], "vetoed", reason)

    def unveto(self, task_id: str):
        task = self.get(task_id)
        if not task or task["state"] != "vetoed":
            raise ValueError("task is not vetoed")
        return self.transition(task_id, "vetoed", "requested", "Veto explicitly lifted; approval required")

    def recover(self):
        """Mark interrupted jobs for review, never automatically retry them."""
        result = self.db.execute(
            "UPDATE tasks SET state='interrupted', updated_at=?, "
            "detail='Worker restarted; manual review required' WHERE state='running'",
            (now(),))
        return result.rowcount
