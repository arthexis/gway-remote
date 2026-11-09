"""Offline bounded deployment broker tests: no deployment subprocesses."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gway_remote import mcp_deployment_broker as broker

SHA = "a" * 40
DECL = {"schema": 1, "checkout": "/tmp/managed-provider",
        "runner": "/tmp/managed-provider/deploy.sh", "run_as": "arthe",
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
            self.assertTrue(second["skipped"])
            self.assertEqual(len(calls), 1)
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

    def test_git_metadata_symlink_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory) / "checkout"
            checkout.mkdir()
            runner = checkout / "deploy.sh"
            runner.write_text("#!/bin/sh\\nexit 0\\n")
            runner.chmod(0o700)
            (checkout / ".git").symlink_to("/tmp")
            declaration = {**DECL, "checkout": str(checkout), "runner": str(runner),
                           "run_as": __import__("pwd").getpwuid(os.geteuid()).pw_name}
            with self.assertRaises(PermissionError):
                broker._eligible("agentops", resolve=lambda _: declaration)

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
