"""Issue #636: repair URL is attempted before executor identity diagnostics.

Hermetic tests for the standalone downloadable bootstrap client. They neither
contact Watchtower nor inspect/modify SSH, accounts, or WireGuard state.
"""
import contextlib
import io
import json
import subprocess
import unittest
from unittest import mock

from gway_remote import wireguard_satellite as satellite


class RepairFirstBootstrapTests(unittest.TestCase):
    def _invoke(self, repair=True):
        argv = ["bootstrap", "--device", "gway-002", "--server-public-key", "unused"]
        if repair:
            argv.append("--repair")
        output = io.StringIO()
        with (mock.patch.object(satellite.getpass, "getpass", return_value="x" * 40),
              mock.patch.object(satellite, "bootstrap", return_value={
                  "device": "gway-002", "configured": True, "reused": True,
                  "host_identity_repaired": True,
              }) as operation,
              mock.patch.object(satellite, "resolve_executor_user",
                                side_effect=ValueError("account mismatch")) as selector,
              mock.patch.object(satellite, "persist_executor_user") as persist,
              mock.patch.object(satellite, "prepare_dormant_executor") as prepare,
              contextlib.redirect_stdout(output)):
            if repair:
                satellite.main(argv)
                self.assertTrue(json.loads(output.getvalue())["host_identity_repaired"])
                operation.assert_called_once()
                selector.assert_not_called()
                persist.assert_not_called()
                prepare.assert_not_called()
            else:
                with self.assertRaises(SystemExit) as failure:
                    satellite.main(argv)
                self.assertEqual(failure.exception.code, 1)
                operation.assert_not_called()
                selector.assert_called_once()
        return output.getvalue()

    def test_repair_does_not_preflight_executor_identity(self):
        self._invoke(repair=True)

    def test_fresh_enrollment_keeps_non_root_identity_gate(self):
        self._invoke(repair=False)

    def test_repair_error_is_reported_after_attempt_without_leaking_detail(self):
        message = "private token must never appear"
        stream = io.StringIO()
        with (mock.patch.object(satellite.getpass, "getpass", return_value="x" * 40),
              mock.patch.object(satellite, "bootstrap",
                                side_effect=ValueError(message)) as repair,
              mock.patch.object(satellite, "resolve_executor_user") as resolver,
              contextlib.redirect_stderr(stream)):
            with self.assertRaises(SystemExit) as outcome:
                satellite.main(["bootstrap", "--device", "gway-002",
                                "--server-public-key", "unused", "--repair"])
        self.assertEqual(outcome.exception.code, 1)
        repair.assert_called_once()
        resolver.assert_not_called()
        self.assertIn("tunnel_identity_or_config", stream.getvalue())
        self.assertNotIn(message, stream.getvalue())

    def test_diagnostics_never_echo_exception_details(self):
        secret = "SECRET-URL-INVITATION"
        cases = [
            ("invitation", ValueError(secret), "invitation"),
            ("executor", ValueError(secret), "executor_provisioning"),
            ("tunnel", PermissionError(secret), "local_permissions_or_conflict"),
            ("tunnel", RuntimeError(secret), "enrollment_or_service"),
            ("tunnel", subprocess.CalledProcessError(1, secret), "local_command"),
            ("tunnel", ValueError(secret), "tunnel_identity_or_config"),
        ]
        for stage, exc, expected in cases:
            with self.subTest(stage=stage, exception=type(exc).__name__):
                category = satellite._bootstrap_failure_category(stage, exc)
                self.assertEqual(category, expected)
                self.assertNotIn(secret, category)


if __name__ == "__main__":
    unittest.main()
