import json
import tempfile
import unittest
from pathlib import Path

from gway_remote.github_health import REPOSITORIES, read_snapshot
from gway_remote.github_health_watch import collect, check


class FakeAPI:
    def __init__(self, fail=False):
        self.paths = []
        self.fail = fail

    def get(self, path):
        self.paths.append(path)
        if self.fail and "ocpp-simulator" in path:
            raise OSError("GitHub unavailable")
        if "/pulls?" in path:
            return []
        if "/protection/required_status_checks" in path:
            return {"contexts": [], "checks": []}
        return {"workflow_runs": []}


class WatchTests(unittest.TestCase):
    def test_three_read_only_requests_per_repo(self):
        api = FakeAPI()
        rows = collect(api)
        self.assertEqual([r["name"] for r in rows], list(REPOSITORIES))
        self.assertEqual(len(api.paths), 15)
        self.assertTrue(all("/pulls?" in p or "/actions/runs?" in p or "/protection/required_status_checks" in p for p in api.paths))

    def test_snapshot_and_sqlite(self):
        with tempfile.TemporaryDirectory() as root:
            db = Path(root) / "observations.sqlite3"
            target = Path(root) / "snapshot.json"
            check(FakeAPI(), db, target)
            self.assertEqual(read_snapshot(target)["status"], "available")
            self.assertTrue(db.is_file())

    def test_failure_does_not_replace_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as root:
            db = Path(root) / "observations.sqlite3"
            target = Path(root) / "snapshot.json"
            check(FakeAPI(), db, target)
            before = target.read_bytes()
            with self.assertRaises(OSError):
                check(FakeAPI(fail=True), db, target)
            self.assertEqual(target.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
