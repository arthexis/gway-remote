"""Watchtower registry transport rejects untrusted SSH and invalid snapshots."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from gway_remote.watchtower_inspection_client import fetch_snapshot


class WatchtowerTransportTests(unittest.TestCase):
    def test_pinned_identity_and_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "ssh.conf"
            config.write_text("Host watchtower-inspection\n")
            config.chmod(0o600)
            effective = ("hostname gelectriic.com\nbatchmode yes\n"
                         "stricthostkeychecking yes\n"
                         "userknownhostsfile /etc/ssh/ssh_known_hosts\n"
                         "identityfile /etc/gway-remote/watchtower-key\n")
            runner = Mock(side_effect=[
                subprocess.CompletedProcess([], 0, effective, ""),
                subprocess.CompletedProcess([], 0, json.dumps({"schema": 2, "nodes": []}), ""),
            ])
            with patch("gway_remote.inspection_ssh_trust.validate_profile"):\n                self.assertEqual(fetch_snapshot(config=config, runner=runner)["schema"], 2)
            self.assertEqual(runner.call_count, 1)

    def test_missing_profile_fails(self):
        with self.assertRaises((ValueError, OSError)):
            fetch_snapshot(config="/nonexistent/inspection-ssh.conf")
