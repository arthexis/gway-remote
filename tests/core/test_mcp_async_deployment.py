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
            first = broker.accept("sample", "b" * 32, expected_revision="a"*40, state_dir=state,
                                  resolve=lambda _: declaration, spawn=spawn)
            self.assertEqual(first["state"], "accepted")
            with patch.object(broker.subprocess, "Popen", side_effect=AssertionError("redispatched")):
                second = broker.accept("sample", "b" * 32, expected_revision="a"*40, state_dir=state,
                                       resolve=lambda _: declaration)
            self.assertEqual(second, first)
            with self.assertRaises(PermissionError):
                broker.request_status("other", "b" * 32, state_dir=state,
                                      resolve=lambda _: declaration)

    def test_concurrent_worker_claim_cannot_execute_twice(self):
        import fcntl
        with tempfile.TemporaryDirectory() as root:
            state = Path(root)
            os.chmod(state, 0o700)
            runner = state / "deploy.sh"
            runner.write_text("#!/bin/sh\\nexit 0\\n")
            runner.chmod(0o700)
            declaration = {"checkout": str(state), "runner": str(runner),
                           "revision": "a"*40}
            resolve = lambda _: declaration
            broker.accept("sample", "4"*32, expected_revision="a"*40, state_dir=state,
                          resolve=resolve, spawn=lambda *a, **k: Mock())
            lock_path = state / (".request-lock-request-" + "4"*32)
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.object(broker, "run", side_effect=AssertionError("executed")):
                    with self.assertRaises(BlockingIOError):
                        broker.worker("sample", "4"*32, state_dir=state, resolve=resolve)
            finally:
                os.close(fd)
            with patch.object(broker, "run", return_value={"state": "succeeded", "exit_code": 0}) as run:
                self.assertEqual(broker.worker("sample", "4"*32, state_dir=state,
                                               resolve=resolve)["state"], "succeeded")
                run.assert_called_once()

    def test_interrupted_running_receipt_is_uncertain_without_restart(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root)
            os.chmod(state, 0o700)
            runner = state / "deploy.sh"
            runner.write_text("#!/bin/sh\\nexit 0\\n")
            runner.chmod(0o700)
            declaration = {"checkout": str(state), "runner": str(runner),
                           "revision": "a"*40}
            resolve = lambda _: declaration
            broker.accept("sample", "3"*32, expected_revision="a"*40, state_dir=state,
                          resolve=resolve, spawn=lambda *a, **k: Mock())
            receipt = broker.request_status("sample", "3"*32, state_dir=state,
                                            resolve=resolve)
            receipt["state"] = "running"
            broker._write_receipt(state / ("request-" + "3"*32 + ".json"), receipt)
            # No held worker lock after a crash/restart: do not claim success.
            observed = broker.request_status("sample", "3"*32, state_dir=state,
                                             resolve=resolve)
            self.assertEqual(observed["state"], "uncertain")
            self.assertEqual(observed["recorded_state"], "running")
            with patch.object(broker.subprocess, "Popen", side_effect=AssertionError("replayed")):
                duplicate = broker.accept("sample", "3"*32, expected_revision="a"*40, state_dir=state,
                                          resolve=resolve)
            self.assertEqual(duplicate["state"], "uncertain")

    def test_orphan_accepted_after_restart_is_uncertain_without_redispatch(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root)
            os.chmod(state, 0o700)
            runner = state / "deploy.sh"
            runner.write_text("#!/bin/sh\\nexit 0\\n")
            runner.chmod(0o700)
            declaration = {"checkout": str(state), "runner": str(runner),
                           "revision": "a"*40}
            resolve = lambda _: declaration
            rid = "7"*32
            broker.accept("sample", rid, expected_revision="a"*40, state_dir=state,
                          resolve=resolve, spawn=lambda *a, **k: Mock())
            path = state / ("request-" + rid + ".json")
            receipt = broker.request_status("sample", rid, state_dir=state,
                                            resolve=resolve)
            self.assertEqual(receipt["state"], "accepted")
            receipt["started_at"] = "2020-01-01T00:00:00+00:00"
            broker._write_receipt(path, receipt)
            observed = broker.request_status("sample", rid, state_dir=state,
                                             resolve=resolve)
            self.assertEqual(observed["state"], "uncertain")
            self.assertEqual(observed["recorded_state"], "accepted")
            with patch.object(broker.subprocess, "Popen",
                              side_effect=AssertionError("redispatch")):
                duplicate = broker.accept("sample", rid, expected_revision="a"*40, state_dir=state,
                                          resolve=resolve)
            self.assertEqual(duplicate["state"], "uncertain")
            # Original worker may still claim its durable accepted receipt.
            with patch.object(broker, "run",
                              return_value={"state": "succeeded", "exit_code": 0}) as run:
                self.assertEqual(broker.worker("sample", rid, state_dir=state,
                                               resolve=resolve)["state"], "succeeded")
                run.assert_called_once()

    def test_partial_claim_is_never_replayed(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root)
            os.chmod(state, 0o700)
            runner = state / "deploy.sh"
            runner.write_text("#!/bin/sh\\nexit 0\\n")
            runner.chmod(0o700)
            declaration = {"checkout": str(state), "runner": str(runner),
                           "revision": "a"*40}
            partial = state / ("request-" + "2"*32 + ".json")
            partial.write_text("{")
            partial.chmod(0o600)
            with patch.object(broker.subprocess, "Popen", side_effect=AssertionError("redispatched")):
                receipt = broker.accept("sample", "2"*32, expected_revision="a"*40, state_dir=state,
                                        resolve=lambda _: declaration)
            self.assertEqual(receipt["state"], "uncertain")

    def test_manifest_change_after_acceptance_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root)
            os.chmod(state, 0o700)
            runner = state / "deploy.sh"
            runner.write_text("#!/bin/sh\\nexit 0\\n")
            runner.chmod(0o700)
            declaration = {"checkout": str(state), "runner": str(runner),
                           "revision": "a"*40}
            broker.accept("sample", "1"*32, expected_revision="a"*40, state_dir=state,
                          resolve=lambda _: declaration, spawn=lambda *a, **k: Mock())
            changed = {**declaration, "revision": "b"*40}
            with self.assertRaises(PermissionError):
                broker.worker("sample", "1"*32, state_dir=state, resolve=lambda _: changed)
            with self.assertRaises(PermissionError):
                broker.accept("sample", "1"*32, expected_revision="a"*40, state_dir=state,
                              resolve=lambda _: changed, spawn=lambda *a, **k: Mock())

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
            first = broker.accept("sample", "d"*32, expected_revision="a"*40, state_dir=state,
                                  resolve=lambda _: declaration, spawn=fail)
            self.assertEqual(first["state"], "uncertain")
            second = broker.accept("sample", "d"*32, expected_revision="a"*40, state_dir=state,
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
            broker.accept("sample", "e"*32, expected_revision="a"*40, state_dir=state,
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
            broker.accept("sample", "f"*32, expected_revision="a"*40, state_dir=state,
                          resolve=resolve, spawn=lambda *a, **k: Mock())
            with patch.object(broker, "run", side_effect=SystemExit(7)):
                with self.assertRaises(SystemExit):
                    broker.worker("sample", "f"*32, state_dir=state, resolve=resolve)
            self.assertEqual(broker.request_status("sample", "f"*32, state_dir=state,
                                                    resolve=resolve)["state"], "uncertain")
            with self.assertRaises(PermissionError):
                broker.worker("sample", "f"*32, state_dir=state, resolve=resolve)


if __name__ == "__main__":
    unittest.main()
