import json
import tempfile
import unittest
from pathlib import Path

from gway_remote.installed import installed_revision, verify_installed


class TestInstalledRevision(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.sha = "a" * 40

    def write(self, data):
        (self.path / "ocpp-csms.json").write_text(json.dumps(data), encoding="utf-8")

    def test_missing_marker_fails_closed(self):
        self.assertIsNone(installed_revision("ocpp-csms", self.path))
        self.assertFalse(verify_installed("ocpp-csms", self.sha, self.path, lambda _: True))

    def test_attestation_requires_health(self):
        self.write({"component": "ocpp-csms", "sha": self.sha})
        self.assertFalse(verify_installed("ocpp-csms", self.sha, self.path, lambda _: False))
        self.assertTrue(verify_installed("ocpp-csms", self.sha, self.path, lambda _: True))

    def test_rejects_wrong_target_and_revision(self):
        self.write({"component": "ocpp-simulator", "sha": self.sha})
        self.assertFalse(verify_installed("ocpp-csms", self.sha, self.path, lambda _: True))
        self.write({"component": "ocpp-csms", "sha": "not-a-sha"})
        self.assertIsNone(installed_revision("ocpp-csms", self.path))

    def test_unknown_component_is_not_accepted(self):
        with self.assertRaises(ValueError):
            installed_revision("other", self.path)


if __name__ == "__main__":
    unittest.main()
