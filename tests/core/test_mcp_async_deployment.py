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

    def test_worker_claim_is_terminal_and_never_reexecuted(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root)
            os.chmod(state, 0o700)
            runner = state / "deploy.sh"
            runner.write_text("#!/bin/sh\\nexit 0\\n")
            runner.chmod(0o700)
            declaration = {"checkout": str(state), "runner": str(runner),
                           "revision": "a"*40}
            resolve = lambda _: declaration
            broker.accept("sample", "e"*32, state_dir=state,
                          resolve=resolve, spawn=lambda *a, **k: Mock())
            with patch.object(broker, "run", return_value={"state": "succeeded", "exit_code": 0}) as execute:
                receipt = broker.worker("sample", "e"*32, state_dir=state, resolve=resolve)
                self.assertEqual(receipt["state"], "succeeded")
                with self.assertRaises(PermissionError):
                    broker.worker("sample", "e"*32, state_dir=state, resolve=resolve)
                execute.assert_called_once()

    def test_unfinished_receipt_is_not_implicitly_restarted(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root)
            os.chmod(state, 0o700)
            runner = state / "deploy.sh"
            runner.write_text("#!/bin/sh\\nexit 0\\n")
            runner.chmod(0o700)
            declaration = {"checkout": str(state), "runner": str(runner),
                           "revision": "a"*40}
            resolve = lambda _: declaration
            broker.accept("sample", "f"*32, state_dir=state,
                          resolve=resolve, spawn=lambda *a, **k: Mock())
            with patch.object(broker, "run", side_effect=SystemExit(7)):
                with self.assertRaises(SystemExit):
                    broker.worker("sample", "f"*32, state_dir=state, resolve=resolve)
            self.assertEqual(broker.request_status("sample", "f"*32, state_dir=state,
                                                    resolve=resolve)["state"], "running")
            with self.assertRaises(PermissionError):
                broker.worker("sample", "f"*32, state_dir=state, resolve=resolve)


if __name__ == "__main__":
    unittest.main()
