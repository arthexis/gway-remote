import unittest
from gway_remote.__main__ import validate


class WorkloadPolicyTests(unittest.TestCase):
    def test_health_no_input(self):
        validate("system-health")

    def test_health_rejects_payload(self):
        with self.assertRaises(ValueError):
            validate("system-health", "arthexis/ocpp-csms", "")

    def test_unknown_task(self):
        with self.assertRaises(ValueError):
            validate("arbitrary-command")

    def test_allowed_simulator(self):
        validate("ocpp-simulator", "arthexis/ocpp-csms", "a" * 40)

    def test_repository_denied(self):
        with self.assertRaises(ValueError):
            validate("ocpp-simulator", "evil/repo", "a" * 40)

    def test_mutable_ref_denied(self):
        with self.assertRaises(ValueError):
            validate("ocpp-simulator", "arthexis/ocpp-csms", "main")


if __name__ == "__main__":
    unittest.main()
