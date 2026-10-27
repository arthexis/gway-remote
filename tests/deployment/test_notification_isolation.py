"""Deployment test mode must not touch the operator's notification surfaces."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.deployment_sound import DeploymentSound, installation_finished


class NotificationIsolationTests(unittest.TestCase):
    def test_disabled_notifications_leave_realistic_home_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.dict(os.environ, {"HOME": str(home), "GWAY_REMOTE_SOUND_DISABLE": "1"}), \
                 patch("pathlib.Path.home", return_value=home), \
                 patch("subprocess.run") as run:
                notification = DeploymentSound("ocpp-csms", revision="a" * 40)
                for event in ("deploy-started", "deploy-failed", "deploy-activated"):
                    notification(event)
                installation_finished(notification, "ocpp-csms", "a" * 40)
                run.assert_not_called()
            self.assertFalse((home / ".local/state/gway-remote/deployment-sounds.sqlite3").exists())
            self.assertFalse((home / ".local/state/lcd-lockfiles").exists())


if __name__ == "__main__":
    unittest.main()
