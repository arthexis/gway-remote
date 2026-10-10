import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.health import component_health, verify_component


class HealthTests(unittest.TestCase):
    def test_csms_never_claims_health_without_service_probe(self):
        self.assertFalse(component_health("ocpp-csms"))

    def test_unknown_target_fails_closed(self):
        self.assertFalse(component_health("unknown"))

    def test_missing_attestation_blocks_healthy_simulator(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("gway_remote.health.component_health", return_value=True):
                self.assertFalse(verify_component("ocpp-simulator", "a" * 40, directory))

    def test_missing_executable_fails_simulator(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("pathlib.Path.home", return_value=Path(directory)):
                self.assertFalse(component_health("ocpp-simulator"))


if __name__ == "__main__":
    unittest.main()
