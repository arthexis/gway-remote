"""Deployment inventory must never confuse attempts with installed revisions."""
import unittest
from unittest.mock import patch
from gway_remote.deployments import inventory, format_inventory


class FakeGitHub:
    def get(self, path):
        return {"commit": {"sha": "abcdef123456" + "0" * 28}}


class DeploymentInventoryTests(unittest.TestCase):
    @patch("gway_remote.deployments.main_head", return_value="abcdef123456" + "0" * 28)
    def test_unknown_installed_not_assumed_from_successful_attempt(self, head):
        report = inventory("ocpp-csms", client=FakeGitHub(),
                           attempts={"ocpp-csms": {"sha": "abcdef123456" + "0" * 28,
                               "status": "installed", "at": "2026-10-17T10:00:00+00:00"}},
                           installed=lambda _: None)
        row = report["components"][0]
        self.assertEqual(row["revision_status"], "unknown")
        self.assertIsNone(row["installed_sha"])
        self.assertEqual(row["attempt_status"], "installed")
        self.assertEqual(row["attempted_at"], "2026-10-17T10:00:00+00:00")
        self.assertIn("unknown", format_inventory(report))

    @patch("gway_remote.deployments.main_head", return_value="abcdef123456" + "0" * 28)
    def test_current_and_behind(self, head):
        current = inventory("ocpp-csms", client=FakeGitHub(), attempts={},
                            installed=lambda _: "abcdef123456")
        self.assertEqual(current["components"][0]["revision_status"], "current")
        behind = inventory("ocpp-csms", client=FakeGitHub(), attempts={},
                           installed=lambda _: "111111111111")
        self.assertEqual(behind["components"][0]["revision_status"], "behind")

    def test_invalid_repository(self):
        with self.assertRaises(ValueError):
            inventory("unlisted-repo", client=FakeGitHub(), attempts={})


if __name__ == "__main__":
    unittest.main()
