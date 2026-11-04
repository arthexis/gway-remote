"""Bounded, best-effort deployment audio; no deployment authority lives here."""
from datetime import datetime, timedelta, timezone
import os
import tempfile
from pathlib import Path
import sqlite3
import subprocess
import time
import uuid

EVENT_PRIORITY = {
    "deploy-started": 10,
    "deploy-activated": 20,
    "deploy-skipped": 30,
    "deploy-verified": 40,
    "deploy-failed": 50,
    "rollback-started": 60,
    "rollback-verified": 70,
    "rollback-failed": 80,
}
EVENTS = frozenset(EVENT_PRIORITY)
TERMINAL_EVENTS = frozenset({
    "deploy-verified", "deploy-skipped", "deploy-failed",
    "rollback-verified", "rollback-failed",
})


class DeploymentSound:
    """Deduplicate by attempt ID, target and event, retaining seven days of receipts.

    IDs are unique per execution, allowing an explicit retry of the same SHA.
    Audio failures, including missing sound installations, never escape.
    """

    def __init__(self, target, deployment_id=None, *, database=None, run=None, revision=None):
        self.revision = revision
        self.target = target
        self.deployment_id = deployment_id or uuid.uuid4().hex
        self.created_at = time.time_ns()
        self.database = Path(database) if database is not None else (
            Path.home() / ".local/state/gway-remote/deployment-sounds.sqlite3")
        self.run = run or subprocess.run

    def __call__(self, event):
        if event not in EVENTS or os.environ.get("GWAY_REMOTE_SOUND_DISABLE") == "1":
            return
        try:
            self.database.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.database, timeout=2) as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("CREATE TABLE IF NOT EXISTS emitted (deployment TEXT, target TEXT, event TEXT, at REAL, PRIMARY KEY(deployment,target,event))")
                db.execute("""CREATE TABLE IF NOT EXISTS lcd_progress (
                    target TEXT PRIMARY KEY, deployment TEXT NOT NULL,
                    created_at INTEGER NOT NULL, priority INTEGER NOT NULL,
                    updated_at REAL NOT NULL)""")
                now = time.time()
                db.execute("DELETE FROM emitted WHERE at < ?", (now - 7 * 86400,))
                inserted = db.execute("INSERT OR IGNORE INTO emitted VALUES (?,?,?,?)",
                                      (self.deployment_id, self.target, event, now)).rowcount
                if not inserted:
                    return
                previous = db.execute(
                    "SELECT deployment,created_at,priority FROM lcd_progress WHERE target=?",
                    (self.target,)).fetchone()
                rank = EVENT_PRIORITY[event]
                # A later stage wins within an attempt. A newer attempt may
                # start again, but a delayed event from an older attempt cannot
                # replace its screen. Hold the DB write lock through the LCD
                # atomic replacement to serialize concurrent producers.
                permitted = (previous is None or
                             (previous[0] == self.deployment_id and rank > previous[2]) or
                             (previous[0] != self.deployment_id and
                              self.created_at > previous[1]))
                if permitted:
                    db.execute("""INSERT INTO lcd_progress VALUES (?,?,?,?,?)
                                  ON CONFLICT(target) DO UPDATE SET
                                  deployment=excluded.deployment,
                                  created_at=excluded.created_at,
                                  priority=excluded.priority,
                                  updated_at=excluded.updated_at""",
                               (self.target, self.deployment_id,
                                self.created_at, rank, now))
                    self._lcd(event)
            self.run([str(Path.home() / ".local/bin/sound"), "--event", event,
                      "--source", "gway-remote"], timeout=3, check=False,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def _lcd(self, event):
        """Publish through the existing event-lockfile runner, never direct I2C."""
        try:
            directory = Path.home() / ".local/state/lcd-lockfiles"
            directory.mkdir(parents=True, exist_ok=True)
            state = event.removeprefix("deploy-").replace("rollback-", "rb-")
            line1 = self.target[:16]
            line2 = f"{state} {(self.revision or '')[:7]}".strip()[:16]
            seconds = 60 if event in TERMINAL_EVENTS else 30
            expires = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
            fd, temporary = tempfile.mkstemp(prefix=".lcd-deploy-", dir=directory)
            try:
                with os.fdopen(fd, "w", encoding="ascii") as stream:
                    stream.write(f"{line1}\n{line2}\n{expires}\n")
                os.replace(temporary, directory / "lcd-event-deployment.lck")
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        except Exception:
            pass


def installation_finished(notify, name, sha):
    """A staged release is silent; only independent evidence earns success audio."""
    if os.environ.get("GWAY_REMOTE_SOUND_DISABLE") == "1" or name == "gway-bastion":
        return
    notify("deploy-activated")
    try:
        from .status import installed_revision
        from .health import component_health
        installed = installed_revision(name)
        if (installed and len(installed) >= 12 and sha.lower().startswith(installed.lower())
                and component_health(name) is True):
            notify("deploy-verified")
    except Exception:
        # Missing verification evidence must never become a success sound.
        pass

