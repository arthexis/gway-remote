import tempfile
import unittest
from pathlib import Path
from gway_remote.attempts import mark
from gway_remote.status import status, format_status


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)

    def test_no_history(self):
        result = status(self.path, probe=lambda _: True)
        self.assertEqual(len(result["components"]), 3)
        self.assertTrue(all(x["installation"] == "never-attempted" for x in result["components"]))
        self.assertTrue(all(x["installed_sha"] is None for x in result["components"]))

    def test_outcomes(self):
        for name, outcome in (("ocpp-csms", "installed"),
                              ("ocpp-simulator", "failed"),
                              ("gway-lcd-sound", "started")):
            mark(name, "a" * 40, outcome, self.path)
        result = status(self.path, probe=lambda _: False)
        self.assertEqual([x["installation"] for x in result["components"]],
                         ["installed", "failed", "interrupted"])
        self.assertIn("ocpp-csms", format_status(result))

    def test_bad_journal(self):
        (self.path / "attempts.json").write_text("invalid")
        result = status(self.path, probe=lambda _: None)
        self.assertTrue(all(x["installation"] == "unknown" for x in result["components"]))

    def test_quick_never_claims_runtime_health(self):
        from unittest.mock import patch
        with patch("gway_remote.status.quick_component_check", return_value="service-active") as quick:
            result = status(self.path, probe=lambda _: self.fail("deep probe called"), depth="quick")
        self.assertEqual(result["depth"], "quick")
        self.assertEqual(quick.call_count, 3)
        self.assertTrue(all(c["health"] == "unknown" and
                            c["evidence"] == "service-active" for c in result["components"]))

    def test_deep_remains_default(self):
        result = status(self.path, probe=lambda _: True)
        self.assertEqual(result["depth"], "deep")
        self.assertTrue(all(c["health"] == "healthy" for c in result["components"]))

    def test_invalid_depth(self):
        with self.assertRaises(ValueError):
            status(self.path, depth="invalid")

    def test_probe_exception(self):
        def fail(_):
            raise OSError("unavailable")
        self.assertEqual(status(self.path, probe=fail)["components"][0]["health"], "unknown")
