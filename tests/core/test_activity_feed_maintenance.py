from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from gway_remote.activity_feed import ActivityFeedStore
from gway_remote.activity_feed_maintenance import status, copy_database, prune
from gway_remote.activity_feed_quota import configure
from gway_remote.activity_feed_http import validate_grants
from tests.core.test_activity_feed import event

class MaintenanceTests(unittest.TestCase):
    def test_backup_restore_new_and_retention(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "feed.sqlite"
            now = datetime.now(timezone.utc) - timedelta(days=181)
            store = ActivityFeedStore(path, clock=lambda: now)
            path.chmod(0o600)
            record, _ = store.append(event(), producer="test", allowed_source="/gway/deploy")
            self.assertEqual(status(path)["events"], 1)
            backup = root / "backup.sqlite"
            restored = root / "restored.sqlite"
            copy_database(path, backup)
            copy_database(backup, restored)
            self.assertEqual(ActivityFeedStore(restored).get(record["seq"]), record)
            with self.assertRaises(FileExistsError):
                copy_database(path, restored)
            self.assertEqual(prune(path)["removed"], 1)
            self.assertEqual(status(path)["events"], 0)
            self.assertEqual(status(restored)["events"], 1)

    def test_page_budget_and_policy(self):
        with sqlite3.connect(":memory:") as db:
            configure(db, 65536, 8192)
            self.assertLessEqual(db.execute("PRAGMA max_page_count").fetchone()[0] *
                                 db.execute("PRAGMA page_size").fetchone()[0], 65536)
        grant = {"enabled":True,"source":"/test","nodes":[None],"repositories":[None],"types":["backup.verified"]}
        self.assertEqual(len(validate_grants({"a"*24:grant})),1)
        for bad in (["*"],[None],["backup.verified","backup.verified"]):
            with self.assertRaises(ValueError):
                validate_grants({"a"*24:{**grant,"types":bad}})
