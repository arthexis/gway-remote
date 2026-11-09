"""Offline durable claim and no redispatch contracts."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from gway_remote import mcp_deployment_broker as broker


class AsyncDeploymentTests(unittest.TestCase):
    def test_receipt_written_before_spawn_and_duplicate_not_spawned(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root)
            os.chmod(state, 0o700)
            declaration = {"checkout": str(state), "runner": str(state / "deploy.sh"),
                           "revision": "a" * 40}
            runner = state / "deploy.sh"
            runner.write_text("#!/bin/sh\nexit 0\n")
            runner.chmod(0o700)
            def spawn(*args, **kwargs):
                receipt = broker.request_status("sample", "b" * 32,
                                                state_dir=state, resolve=lambda _: declaration)
                self.assertEqual(receipt["state"], "accepted")
                return Mock()
            first = broker.accept("sample", "b" * 32, state_dir=state,
                                  resolve=lambda _: declaration, spawn=spawn)
            self.assertEqual(first["state"], "accepted")
            with patch.object(broker.subprocess, "Popen", side_effect=AssertionError("redispatched")):
                second = broker.accept("sample", "b" * 32, state_dir=state,
                                       resolve=lambda _: declaration)
            self.assertEqual(second, first)
            with self.assertRaises(PermissionError):
                broker.request_status("other", "b" * 32, state_dir=state,
                                      resolve=lambda _: declaration)

    def test_failed_spawn_does_not_retry_after_restart(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root)
            os.chmod(state, 0o700)
            runner = state / "deploy.sh"
            runner.write_text("#!/bin/sh\nexit 0\n")
            runner.chmod(0o700)
            declaration = {"checkout": str(state), "runner": str(runner), "revision": "c"*40}
            def fail(*args, **kwargs):
                raise OSError("unavailable")
            first = broker.accept("sample", "d"*32, state_dir=state,
                                  resolve=lambda _: declaration, spawn=fail)
            self.assertEqual(first["state"], "uncertain")
            second = broker.accept("sample", "d"*32, state_dir=state,
                                   resolve=lambda _: declaration, spawn=fail)
            self.assertEqual(second, first)


if __name__ == "__main__":
    unittest.main()
