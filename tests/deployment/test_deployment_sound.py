"""Audio deduplication and verification boundaries without hardware."""
import os
from pathlib import Path
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import Mock, patch

from gway_remote.deployment_sound import DeploymentSound, installation_finished


class DeploymentSoundTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"GWAY_REMOTE_SOUND_DISABLE": "0"})
        environment.start()
        self.addCleanup(environment.stop)

    def test_deduplicates_across_instances_and_targets_and_allows_retry(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"GWAY_REMOTE_SOUND_DISABLE": "0"}):
            database = Path(directory) / "events.db"
            run = Mock()
            with patch.object(DeploymentSound, "_lcd"):
                for target, attempt in (("a", "one"), ("a", "one"), ("b", "one"), ("a", "two")):
                    DeploymentSound(target, attempt, database=database, run=run)("deploy-started")
            self.assertEqual(run.call_count, 3)
            self.assertEqual(run.call_args.args[0][-4:], ["--event", "deploy-started", "--source", "gway-remote"])

    def test_playback_and_state_failures_are_nonfatal(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"GWAY_REMOTE_SOUND_DISABLE": "0"}):
            for error in (FileNotFoundError(), subprocess.TimeoutExpired("sound", 3)):
                sound = DeploymentSound("a", database=Path(directory) / "events.db", run=Mock(side_effect=error))
                with patch.object(sound, "_lcd"):
                    sound("deploy-started")
            blocked = Path(directory) / "file"
            blocked.write_text("blocked")
            DeploymentSound("a", database=blocked / "db", run=Mock())("deploy-failed")

    def test_lcd_uses_existing_lockfile_contract(self):
        with tempfile.TemporaryDirectory() as directory, patch("gway_remote.deployment_sound.Path.home", return_value=Path(directory)):
            DeploymentSound("ocpp-csms", revision="a" * 40)._lcd("deploy-verified")
            path = Path(directory) / ".local/state/lcd-lockfiles/lcd-event-deployment.lck"
            lines = path.read_text().splitlines()
            self.assertEqual(lines[:2], ["ocpp-csms", "verified aaaaaaa"])
            self.assertEqual(len(lines), 3)
            self.assertTrue(all(len(line) <= 16 for line in lines[:2]))

    def test_priority_prevents_regression_and_allows_new_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "events.db"
            calls = []
            with patch.object(DeploymentSound, "_lcd", lambda self, event: calls.append((self.deployment_id, event))):
                old = DeploymentSound("gway-remote", deployment_id="old", database=db, run=Mock())
                old("deploy-started")
                old("deploy-activated")
                old("deploy-verified")
                old("deploy-activated")  # lower stage cannot replace verified
                fresh = DeploymentSound("gway-remote", deployment_id="fresh", database=db, run=Mock())
                fresh("deploy-started")  # a new attempt can restart at low priority
                old("rollback-failed")  # late message from an older run must not replace fresh
                fresh("deploy-skipped")
            self.assertEqual(calls, [
                ("old", "deploy-started"), ("old", "deploy-activated"),
                ("old", "deploy-verified"), ("fresh", "deploy-started"),
                ("fresh", "deploy-skipped"),
            ])

    def test_rollback_outcome_overrides_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            with patch.object(DeploymentSound, "_lcd", lambda self, event: calls.append(event)):
                notifier = DeploymentSound("gway-remote", database=Path(directory) / "db", run=Mock())
                for event in ("deploy-started", "deploy-activated", "deploy-failed",
                              "rollback-started", "rollback-verified", "deploy-started"):
                    notifier(event)
            self.assertEqual(calls, ["deploy-started", "deploy-activated", "deploy-failed",
                                     "rollback-started", "rollback-verified"])

    def test_terminal_event_has_longer_lcd_expiry(self):
        with tempfile.TemporaryDirectory() as directory, patch(
                "gway_remote.deployment_sound.Path.home", return_value=Path(directory)):
            notifier = DeploymentSound("gway-remote", database=Path(directory) / "db", run=Mock())
            path = Path(directory) / ".local/state/lcd-lockfiles/lcd-event-deployment.lck"
            notifier._lcd("deploy-started")
            started = datetime.fromisoformat(path.read_text().splitlines()[2])
            notifier._lcd("deploy-verified")
            verified = datetime.fromisoformat(path.read_text().splitlines()[2])
            self.assertGreater((verified - started).total_seconds(), 25)
            self.assertLess((verified - started).total_seconds(), 35)

    def test_success_requires_matching_revision_and_positive_health(self):
        sha = "a" * 40
        for installed, healthy, expected in ((sha[:12], True, True), (sha, True, True),
                                             ("b" * 40, True, False), (None, True, False),
                                             (sha, None, False), (sha, False, False)):
            with self.subTest(installed=installed, healthy=healthy):
                notify = Mock()
                with patch("gway_remote.status.installed_revision", return_value=installed), patch("gway_remote.health.component_health", return_value=healthy):
                    installation_finished(notify, "ocpp-csms", sha)
                self.assertEqual([c.args[0] for c in notify.call_args_list],
                                 ["deploy-activated"] + (["deploy-verified"] if expected else []))

    def test_staging_never_announces_activation_or_success(self):
        notify = Mock()
        installation_finished(notify, "gway-bastion", "a" * 40)
        notify.assert_not_called()
