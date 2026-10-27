"""Bounded, best-effort deployment audio; no deployment authority lives here."""
from datetime import datetime, timedelta, timezone
import os
import tempfile
from pathlib import Path
import sqlite3
import subprocess
import time
import uuid

EVENTS = frozenset({"deploy-started", "deploy-activated", "deploy-verified",
                    "deploy-failed", "rollback-started", "rollback-verified",
                    "rollback-failed"})


class DeploymentSound:
    """Deduplicate by attempt ID, target and event, retaining seven days of receipts.

    IDs are unique per execution, allowing an explicit retry of the same SHA.
    Audio failures, including missing sound installations, never escape.
    """

    def __init__(self, target, deployment_id=None, *, database=None, run=None, revision=None):
        self.revision = revision
        self.target = target
        self.deployment_id = deployment_id or uuid.uuid4().hex
        self.database = Path(database) if database is not None else (
            Path.home() / ".local/state/gway-remote/deployment-sounds.sqlite3")
        self.run = run or subprocess.run

    def __call__(self, event):
        if event not in EVENTS or os.environ.get("GWAY_REMOTE_SOUND_DISABLE") == "1":
            return
        try:
            self.database.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.database, timeout=0.1) as db:
                db.execute("CREATE TABLE IF NOT EXISTS emitted (deployment TEXT, target TEXT, event TEXT, at REAL, PRIMARY KEY(deployment,target,event))")
                now = time.time()
                db.execute("DELETE FROM emitted WHERE at < ?", (now - 7 * 86400,))
                inserted = db.execute("INSERT OR IGNORE INTO emitted VALUES (?,?,?,?)",
                                      (self.deployment_id, self.target, event, now)).rowcount
            if inserted:
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
            expires = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
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

