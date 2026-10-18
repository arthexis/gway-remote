"""Declarative probe registry contract and safe future-target fallback."""
import unittest
from dataclasses import replace
from unittest.mock import patch

from gway_remote.probe_registry import PROBES, Probe, probe_for
from gway_remote.reconcile import TARGETS
from gway_remote.status import installed_revision
from gway_remote.health import component_health


class ProbeRegistryTests(unittest.TestCase):
    def test_all_targets_have_a_known_or_unknown_probe(self):
        for name, _ in TARGETS:
            self.assertIsInstance(probe_for(name), Probe)
        self.assertEqual(probe_for("future-repo").kind, "unknown")
        self.assertTrue(set(PROBES).issubset({name for name, _ in TARGETS}))

    def test_unknown_probe_is_not_a_failed_health_check(self):
        for name in ("ocpp-reports", "gway-agent-ops", "gway-ap-kiosk"):
            self.assertIsNone(component_health(name))
            self.assertIsNone(installed_revision(name))

    def test_registered_system_unit_drives_existing_probe(self):
        with patch("gway_remote.health._command", return_value=True) as command:
            self.assertTrue(component_health("gway-rfid"))
            self.assertEqual(command.call_args_list[0].args[0][-1], "gway-rfid.service")

    def test_registered_revision_pattern_is_explicit(self):
        self.assertEqual(probe_for("gway-rfid").revision_pattern, r"[0-9a-f]{40}")
        self.assertIsNone(probe_for("ocpp-reports").revision_pattern)


if __name__ == "__main__":
    unittest.main()
