import json
import tempfile
import unittest
from pathlib import Path

from gway_remote.github_health import REPOSITORIES, read_snapshot
from gway_remote.github_health_watch import collect, check, _pr_for_sha


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


class ShaLookupAPI:
    def __init__(self, candidates, details):
        self.candidates = candidates
        self.details = details
        self.paths = []

    def get(self, path):
        self.paths.append(path)
        if "/commits/" in path and "/pulls?" in path:
            page = int(path.split("page=")[-1])
            return self.candidates.get(page, [])
        return self.details[int(path.rsplit("/", 1)[-1])]


class ShaCorrelationTests(unittest.TestCase):
    SHA = "a" * 40

    def test_empty_run_links_match_unique_exact_sha(self):
        api = ShaLookupAPI({1: [{"number": 13}]}, {
            13: {"number": 13, "state": "closed", "head": {"sha": self.SHA}}})
        self.assertEqual(_pr_for_sha(api, "arthexis/gway-ap-kiosk", self.SHA), (13, "closed"))

    def test_reused_branch_and_nonmatching_head_are_not_inferred(self):
        api = ShaLookupAPI({1: [{"number": 1}, {"number": 13}]}, {
            1: {"number": 1, "state": "closed", "head": {"sha": "b" * 40}},
            13: {"number": 13, "state": "closed", "head": {"sha": self.SHA}}})
        self.assertEqual(_pr_for_sha(api, "arthexis/gway-ap-kiosk", self.SHA), (13, "closed"))
        api.details[1]["head"]["sha"] = self.SHA
        self.assertIsNone(_pr_for_sha(api, "arthexis/gway-ap-kiosk", self.SHA))

    def test_unverified_or_open_pr_is_not_closed(self):
        api = ShaLookupAPI({1: [{"number": 13}]}, {
            13: {"number": 13, "state": "open", "head": {"sha": self.SHA}}})
        self.assertEqual(_pr_for_sha(api, "arthexis/gway-ap-kiosk", self.SHA), (13, "open"))
        api.details[13]["state"] = "unexpected"
        self.assertIsNone(_pr_for_sha(api, "arthexis/gway-ap-kiosk", self.SHA))
        self.assertIsNone(_pr_for_sha(api, "arthexis/gway-ap-kiosk", "bad"))

    def test_incomplete_page_fails_closed(self):
        api = ShaLookupAPI({1: None}, {})
        self.assertIsNone(_pr_for_sha(api, "arthexis/gway-ap-kiosk", self.SHA))


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
