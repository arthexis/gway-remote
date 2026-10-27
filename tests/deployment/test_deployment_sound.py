"""Audio deduplication and verification boundaries without hardware."""
import os
from pathlib import Path
import subprocess
import tempfile
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
