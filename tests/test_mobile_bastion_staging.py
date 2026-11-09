import unittest
from unittest.mock import patch

from gway_remote.mobile_deployments import overview


class MobileBastionStagingTests(unittest.TestCase):
    def test_staged_release_does_not_claim_installed_revision(self):
        sha = "a" * 40
        with patch("gway_remote.mobile_deployments.export_targets", return_value={
            "targets": [{"name": "gway-bastion", "repository": "arthexis/gway-bastion"}]
        }):
            result = overview(
                {}, attempts_reader=lambda: {},
                revision_reader=lambda name: None,
                bastion_reader=lambda: {
                    "release_state": "staged", "staged_sha": sha,
                    "activated_sha": None,
                },
            )
        target = result["targets"][0]
        self.assertIsNone(target["installed_sha"])
        self.assertEqual(target["release_state"], "staged")
        self.assertEqual(target["staged_sha"], sha)

    def test_unverified_staging_remains_unknown(self):
        with patch("gway_remote.mobile_deployments.export_targets", return_value={
            "targets": [{"name": "gway-bastion", "repository": "arthexis/gway-bastion"}]
        }):
            target = overview(
                {}, attempts_reader=lambda: {},
                revision_reader=lambda name: None,
                bastion_reader=lambda: {
                    "release_state": "unknown", "staged_sha": None,
                    "activated_sha": None,
                },
            )["targets"][0]
        self.assertEqual(target["release_state"], "unknown")
        self.assertIsNone(target["installed_sha"])


if __name__ == "__main__":
    unittest.main()
