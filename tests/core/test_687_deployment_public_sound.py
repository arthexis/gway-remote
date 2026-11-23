"""Issue #687: real deployment producer uses only normal public sound CLI.

Unittest-discoverable, hermetic, no hardware, SSH, bearer or deployment.
"""
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import subprocess
import unittest
from unittest.mock import patch

from gway_remote.deployment_sound import DeploymentSound


class DeploymentPublicSoundTests(unittest.TestCase):
    def make_notifier(self, tmp, callback):
        n = DeploymentSound("gway-remote", deployment_id="test-attempt",
                            database=Path(tmp) / "attempts.sqlite3", run=callback)
        n._lcd = lambda event: None
        return n

    def test_emits_compatible_public_event_just_once(self):
        with TemporaryDirectory() as tmp:
            calls = []
            def runner(argv, **kwargs):
                calls.append((argv, kwargs))
                return SimpleNamespace(returncode=0)
            n = self.make_notifier(tmp, runner)
            n("deploy-verified")
            n("deploy-verified")  # idempotent even if producer is called twice
            self.assertEqual(len(calls), 1)
            argv, kw = calls[0]
            self.assertEqual(argv, [str(Path.home() / ".local/bin/sound"),
                                    "--event", "deploy-verified",
                                    "--source", "gway-remote", "--within", "30"])
            self.assertEqual(kw["timeout"], 18)
            self.assertFalse(kw["check"])

    def test_failure_does_not_trigger_legacy_fallback(self):
        with TemporaryDirectory() as tmp:
            calls = []
            def runner(argv, **kwargs):
                calls.append(argv)
                return SimpleNamespace(returncode=1)
            n = self.make_notifier(tmp, runner)
            n("deploy-failed")
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], str(Path.home() / ".local/bin/sound"))

    def test_uncertain_outcome_is_not_replayed_or_fallen_back(self):
        with TemporaryDirectory() as tmp:
            calls = []
            def runner(argv, **kwargs):
                calls.append(argv)
                raise subprocess.TimeoutExpired(argv, 3)
            n = self.make_notifier(tmp, runner)
            n("rollback-failed")
            n("rollback-failed")
            self.assertEqual(len(calls), 1)

    def test_missing_public_command_does_not_change_deployment_authority(self):
        with TemporaryDirectory() as tmp:
            calls = []
            def runner(argv, **kwargs):
                calls.append(argv)
                raise FileNotFoundError()
            n = self.make_notifier(tmp, runner)
            self.assertIsNone(n("deploy-started"))
            self.assertEqual(len(calls), 1)

    def test_disable_preserves_silence(self):
        with TemporaryDirectory() as tmp:
            n = self.make_notifier(tmp, lambda *a, **kw: self.fail("no playback"))
            with patch.dict("os.environ", {"GWAY_REMOTE_SOUND_DISABLE": "1"}):
                self.assertIsNone(n("deploy-started"))
