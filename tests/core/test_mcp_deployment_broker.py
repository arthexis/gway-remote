"""Offline bounded deployment broker tests: no deployment subprocesses."""
import os
import fcntl
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gway_remote import mcp_deployment_broker as broker

SHA = "a" * 40
DECL = {"schema": 1, "checkout": "/tmp/managed-provider",
        "runner": "/tmp/managed-provider/deploy.sh",
        "revision": SHA}


class Result:
    returncode = 0


class BrokerTests(unittest.TestCase):
    def test_preview_does_not_execute(self):
        self.assertEqual(broker.preview("agentops", resolve=lambda _: DECL)["status"], "declared")

    def test_receipt_idempotency_and_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            calls = []
            def invoke(*args, **kwargs):
                calls.append((args, kwargs))
                return Result()
            with patch.object(broker, "_eligible", return_value=DECL):
                first = broker.run("agentops", state_dir=state, resolve=lambda _: DECL, invoke=invoke)
                second = broker.run("agentops", state_dir=state, resolve=lambda _: DECL, invoke=invoke)
            self.assertEqual(first["state"], "succeeded")
            self.assertEqual(second["state"], "succeeded")
            self.assertEqual(len(calls), 2)
            self.assertEqual(broker.status("agentops", state_dir=state, resolve=lambda _: DECL)["revision"], SHA)

    def test_failed_runner_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(broker, "_eligible", return_value=DECL):
                receipt = broker.run("agentops", state_dir=Path(directory),
                                     resolve=lambda _: DECL,
                                     invoke=lambda *a, **k: type("Failure", (), {"returncode": 12})())
            self.assertEqual(receipt["state"], "failed")
            self.assertEqual(receipt["exit_code"], 12)

    def test_symlink_receipt_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / "status-agentops.json").symlink_to("/etc/passwd")
            with self.assertRaises(PermissionError):
                broker.status("agentops", state_dir=state, resolve=lambda _: DECL)

    def test_corrupt_or_cross_application_receipt_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            receipt = state / "status-agentops.json"
            for data in ('not-json', '{"application":"other","state":"succeeded"}',
                         '{"application":"agentops","state":"unknown"}'):
                with self.subTest(data=data):
                    receipt.write_text(data)
                    with self.assertRaises(ValueError):
                        broker.status("agentops", state_dir=state, resolve=lambda _: DECL)

    def test_repeated_request_reinvokes_provider_for_active_revision_check(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def invoke(*args, **kwargs):
                calls.append(True)
                return Result()
            with patch.object(broker, "_eligible", return_value=DECL):
                broker.run("agentops", state_dir=Path(directory), resolve=lambda _: DECL, invoke=invoke)
                broker.run("agentops", state_dir=Path(directory), resolve=lambda _: DECL, invoke=invoke)
            self.assertEqual(len(calls), 2)

    def test_concurrent_run_fails_closed_without_invoking_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            lock = state / broker.LOCK_NAME
            with lock.open("w") as stream:
                lock.chmod(0o600)
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.object(broker, "_eligible", return_value=DECL):
                    with self.assertRaises(BlockingIOError):
                        broker.run("agentops", state_dir=state, resolve=lambda _: DECL,
                                   invoke=lambda *a, **k: self.fail("must not execute"))
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def test_world_readable_state_directory_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            state.chmod(0o755)
            try:
                with patch.object(broker, "_eligible", return_value=DECL):
                    with self.assertRaises(PermissionError):
                        broker.run("agentops", state_dir=state, resolve=lambda _: DECL,
                                   invoke=lambda *a, **k: self.fail("must not execute"))
            finally:
                state.chmod(0o700)

    def test_lock_symlink_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / ".managed-provider.lock").symlink_to("/etc/passwd")
            with patch.object(broker, "_eligible", return_value=DECL):
                with self.assertRaises(PermissionError):
                    broker.run("agentops", state_dir=state, resolve=lambda _: DECL,
                               invoke=lambda *a, **k: Result())


if __name__ == "__main__":
    unittest.main()
