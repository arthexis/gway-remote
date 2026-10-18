import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from gway_remote.appliance_watch import eligible, check, _issue, _busy, _reserve_dispatch, _dispatch_reservations
from gway_remote.status import installed_revision


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 18, 20, tzinfo=timezone.utc)
        self.row = {"revision_status": "behind", "attempted_sha": "a" * 40,
                    "attempt_status": "installed", "latest_sha": "b" * 40}

    def test_requires_green_ci_and_cooldown_and_no_prior_attempt(self):
        old = self.now - timedelta(minutes=11)
        self.assertTrue(eligible(self.row, "success", old, self.now))
        self.assertFalse(eligible(self.row, "failure", old, self.now))
        self.assertFalse(eligible(self.row, "success", self.now, self.now))
        self.assertFalse(eligible({**self.row, "attempted_sha": "b" * 40}, "success", old, self.now))
        self.assertFalse(eligible({**self.row, "revision_status": "unknown"}, "success", old, self.now))

    def test_tick_is_dry_run_by_default(self):
        with patch("gway_remote.appliance_watch.read_attempts", return_value={}):
            with patch("gway_remote.appliance_watch.inventory", return_value={"components": [
                {"name": "gway-rfid", "revision_status": "current"}]}):
                with patch("gway_remote.appliance_watch.diagnose", return_value={"components": [
                    {"name": "gway-rfid", "diagnosis": "healthy"}]}):
                    with patch("gway_remote.appliance_watch.dispatch") as dispatch:
                        report = check(client=object(), now=self.now)
                        self.assertIsNone(report["dispatched"])
                        dispatch.assert_not_called()

    def test_issue_reuses_existing_marker_without_rewriting(self):
        from gway_remote.appliance_watch import ISSUE_MARKER
        marker = ISSUE_MARKER.format(name="gway-rfid", kind="runtime-failure")
        body = (f"{marker}\n## Appliance runtime-failure: gway-rfid\n\n"
                "Reader service stopped\n\nSource: gway-remote appliance watch.")
        with patch("gway_remote.appliance_watch._api", return_value=[
            {"number": 42, "body": body}]) as api:
            _issue("arthexis/gway-rfid", "gway-rfid", "runtime-failure", "Reader service stopped")
        self.assertEqual(api.call_count, 1)

    def test_durable_dispatch_reservation_prevents_duplicate_workflows(self):
        with tempfile.TemporaryDirectory() as folder:
            sha = "b" * 40
            self.assertTrue(_reserve_dispatch("ocpp-csms", sha, folder))
            self.assertFalse(_reserve_dispatch("ocpp-csms", sha, folder))
            self.assertEqual(_dispatch_reservations(folder)["ocpp-csms"], sha)
            self.assertTrue(_reserve_dispatch("ocpp-csms", "c" * 40, folder))
            self.assertEqual(_dispatch_reservations(folder)["ocpp-csms"], "c" * 40)

    def test_invalid_dispatch_journal_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "watch-dispatches.json").write_text("invalid")
            with self.assertRaises(ValueError):
                _dispatch_reservations(folder)

    def test_reports_and_agent_sha_read_from_verified_release_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            sha = "a" * 40
            executable = home / ".local/share/gway-agent-ops/releases" / sha / "bin/agent"
            executable.parent.mkdir(parents=True)
            executable.write_text("x")
            link = home / ".local/bin/agent"
            link.parent.mkdir(parents=True)
            link.symlink_to(executable)
            with patch("pathlib.Path.home", return_value=home):
                self.assertEqual(installed_revision("gway-agent-ops"), sha)
                link.unlink()
                link.symlink_to(home / "not-real")
                self.assertIsNone(installed_revision("gway-agent-ops"))


if __name__ == "__main__":
    unittest.main()
