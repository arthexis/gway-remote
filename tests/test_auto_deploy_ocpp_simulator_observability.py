"""Offline negative tests for bounded OCPP simulator deployment diagnostics."""
import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "auto-deploy-ocpp-simulator.py"
spec = importlib.util.spec_from_file_location("simulator_auto_deploy", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
SECRET = "ghp_SECRET_AUTH_TOKEN_123"
STAGES = (
    "preflight", "github_admission", "release_inspection", "checkout",
    "ansible_install", "release_verify", "go_provenance", "final_sha_fence",
)


class SafeDiagnosticsTests(unittest.TestCase):
    def test_each_stage_has_closed_diagnostic(self):
        for name in STAGES:
            with self.subTest(name=name):
                with mock.patch.object(mod.time, "monotonic_ns", side_effect=[1000000, 9000000]):
                    mod.stage(name)
                    value = mod.safe_failure(mod.AdmissionError(SECRET))
                self.assertIn("stage=" + name, value)
                self.assertIn("elapsed_ms=8", value)
                self.assertNotIn(SECRET, value)

    def test_reject_unknown_stage(self):
        with self.assertRaises(ValueError):
            mod.stage("secret=" + SECRET)

    def test_subprocess_error_never_exposes_command_or_streams(self):
        cases = [
            subprocess.CalledProcessError(2, ["git", SECRET], output=SECRET, stderr=SECRET),
            subprocess.TimeoutExpired(["sh", SECRET], 2400, output=SECRET, stderr=SECRET),
            OSError(SECRET),
            ValueError(SECRET),
            mod.AdmissionError(SECRET),
        ]
        for exc in cases:
            with self.subTest(kind=type(exc).__name__):
                mod.stage("ansible_install")
                message = mod.safe_failure(exc)
                self.assertNotIn(SECRET, message)
                self.assertNotIn("git", message)
                self.assertNotIn("sh ", message)
                self.assertIn("stage=ansible_install", message)
        self.assertIn("exit_code=2", mod.safe_failure(cases[0]))
        self.assertIn("exit_code=none", mod.safe_failure(cases[1]))

    def test_main_reports_only_bounded_error(self):
        with mock.patch.object(mod, "auto_install", side_effect=subprocess.CalledProcessError(
            17, ["command", SECRET], output=SECRET, stderr=SECRET
        )):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(mod.main(), 1)
            self.assertIn("exit_code=17", output.getvalue())
            self.assertNotIn(SECRET, output.getvalue())

    def test_main_preserves_skip_up_to_date_and_installed(self):
        for result in ("SKIPPED: no CI", "UP_TO_DATE: verified", "INSTALLED: verified"):
            with self.subTest(result=result), mock.patch.object(mod, "auto_install", return_value=result):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(mod.main(), 0)
                self.assertEqual(output.getvalue().strip(), "::notice::" + result)

    def test_invoke_retains_capture_and_timeout(self):
        result = subprocess.CompletedProcess(["gh"], 0, stdout="ok\n", stderr="")
        with mock.patch.object(mod.subprocess, "run", return_value=result) as run:
            self.assertEqual(mod.invoke(["gh"], timeout=25), "ok")
        self.assertTrue(run.call_args.kwargs["capture_output"])
        self.assertTrue(run.call_args.kwargs["check"])
        self.assertEqual(run.call_args.kwargs["timeout"], 25)


if __name__ == "__main__":
    unittest.main()
