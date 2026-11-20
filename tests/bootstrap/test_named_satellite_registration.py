"""Regression tests for named Watchtower satellite registration."""
import unittest
from gway_remote.wireguard_enrollment_contract import DEVICE
from gway_remote.host_identity import NODE
from gway_remote.watchtower_adopt import _NODE

class NamedSatelliteTests(unittest.TestCase):
    def test_named_host_accepted_consistently(self):
        for validator in (DEVICE, NODE, _NODE):
            for name in ("ocpp-abb-1", "gway-001", "gway-1000"):
                with self.subTest(validator=validator, name=name):
                    self.assertIsNotNone(validator.fullmatch(name))

    def test_invalid_hostnames_rejected(self):
        for validator in (DEVICE, NODE, _NODE):
            for name in ("", "ocpp_abb_1", "-ocpp-abb-1", "ocpp-abb-1-", "OCPP-ABB-1", "ocpp.abb.1", "gway-01", "x", "../escape"):
                with self.subTest(validator=validator, name=name):
                    self.assertIsNone(validator.fullmatch(name))

if __name__ == "__main__":
    unittest.main()
