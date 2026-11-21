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

    def test_short_gway_name_currently_matches_generic_named_host_rule(self):
        # Preserve current named-host behavior; change only by separate contract PR.
        for validator in (DEVICE, NODE, _NODE):
            self.assertIsNotNone(validator.fullmatch("gway-01"))

    def test_invalid_hostnames_rejected(self):
        for validator in (DEVICE, NODE, _NODE):
            for name in ("", "ocpp_abb_1", "-ocpp-abb-1", "ocpp-abb-1-", "OCPP-ABB-1", "ocpp.abb.1", "x", "../escape"):
                with self.subTest(validator=validator, name=name):
                    self.assertIsNone(validator.fullmatch(name))

if __name__ == "__main__":
    unittest.main()
