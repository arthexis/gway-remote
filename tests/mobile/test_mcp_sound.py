"""Bounded MCP execution sounds are nonfatal and never disclose commands."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from gway_remote.mcp_sound import McpOperationSound


class McpOperationSoundTests(unittest.TestCase):
    def test_deduplicates_same_request_and_event(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
                os.environ, {"GWAY_REMOTE_SOUND_DISABLE": "0"}):
            run = Mock()
            db = Path(directory) / "events.sqlite3"
            for request, event in (
                    ("req-1", "mcp-exec-started"), ("req-1", "mcp-exec-started"),
                    ("req-1", "mcp-exec-completed"), ("req-2", "mcp-exec-started")):
                McpOperationSound("gway-001", request, database=db, run=run)(event)
            self.assertEqual(run.call_count, 3)
            self.assertEqual(run.call_args.args[0][-4:],
                             ["--event", "mcp-exec-started", "--source", "gway-remote"])

    def test_denied_or_unknown_events_never_play(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Mock()
            sound = McpOperationSound("gway-001", "req-1",
                                      database=Path(directory) / "events.sqlite3",
                                      run=run)
            sound("mcp-exec-denied")
            sound("node_list")
            run.assert_not_called()

    def test_mute_and_audio_failure_do_not_affect_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "events.sqlite3"
            with patch.dict(os.environ, {"GWAY_REMOTE_SOUND_DISABLE": "1"}):
                run = Mock()
                McpOperationSound("gway-001", "req-1", database=db, run=run)(
                    "mcp-exec-started")
                run.assert_not_called()
            with patch.dict(os.environ, {"GWAY_REMOTE_SOUND_DISABLE": "0"}):
                run = Mock(side_effect=subprocess.TimeoutExpired("sound", 3))
                McpOperationSound("gway-001", "req-1", database=db, run=run)(
                    "mcp-exec-failed")

    def test_validates_only_identity_metadata_not_command_text(self):
        for bad in ("", "../evil", "node;id", "spaces allowed", "a" * 100):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                McpOperationSound(bad, "request-1")
            with self.subTest(bad_request=bad), self.assertRaises(ValueError):
                McpOperationSound("gway-001", bad)
