import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.diagnostics import diagnose, format_diagnosis
from gway_remote.health import component_health
from gway_remote.reconcile import TARGETS


class DiagnosticTests(unittest.TestCase):
    def test_unknown_health_contract_does_not_claim_failure(self):
        self.assertIsNone(component_health("ocpp-reports"))
        self.assertIsNone(component_health("gway-agent-ops"))
        self.assertIsNone(component_health("gway-ap-kiosk"))

    def test_each_registered_target_has_diagnostic_without_side_effects(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("gway_remote.diagnostics._systemd", return_value={"state": "not-configured"}):
                with patch("gway_remote.status.installed_revision", return_value=None):
                    result = diagnose(directory=Path(folder))
        self.assertEqual({c["name"] for c in result["components"]}, {n for n, _ in TARGETS})
        self.assertEqual(result["schema"], "gway-remote/diagnosis/v1")
        self.assertTrue(all(c["recent_installer_log"] == "" for c in result["components"]))

    def test_failed_attempt_is_diagnosed_even_without_health_probe(self):
        from gway_remote.attempts import mark
        with tempfile.TemporaryDirectory() as folder:
            mark("gway-agent-ops", "a" * 40, "failed", Path(folder))
            with patch("gway_remote.diagnostics._systemd", return_value={"state": "not-configured"}):
                report = diagnose("gway-agent-ops", directory=Path(folder))
        self.assertEqual(report["components"][0]["diagnosis"], "installation-failed")
        self.assertIn("installation-failed", format_diagnosis(report))

    def test_invalid_target_and_line_bounds(self):
        with self.assertRaises(ValueError):
            diagnose("other-repo")
        with self.assertRaises(ValueError):
            diagnose(lines=101)

    @patch("gway_remote.diagnostics.subprocess.run")
    def test_systemd_inspection_is_read_only(self, run):
        from gway_remote.diagnostics import _systemd
        run.return_value.returncode = 0
        run.return_value.stdout = "ActiveState=active\\nNRestarts=1\\n"
        self.assertEqual(_systemd("gway-rfid.service")["ActiveState"], "active")
        args = run.call_args.args[0]
        self.assertEqual(args[:2], ["systemctl", "show"])
        self.assertNotIn("restart", args)


if __name__ == "__main__":
    unittest.main()
