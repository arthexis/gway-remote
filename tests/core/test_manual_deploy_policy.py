"""Initial manual deployment authorization contract."""
import unittest

from gway_remote.manual_deploy_policy import validate_deployment


class ManualDeployPolicyTests(unittest.TestCase):
    def test_pilot_targets(self):
        for node in ("gway-001", "ocpp-abb-1"):
            with self.subTest(node=node):
                self.assertEqual(
                    validate_deployment("arthexis/ocpp-reports", node)["revision"],
                    "main",
                )

    def test_unapproved_target_denied(self):
        for node, repo in (
            ("gway-002", "arthexis/ocpp-reports"),
            ("ocpp-abb-1", "arthexis/gway-remote"),
            ("ocpp-abb-1", "arthexis/ocpp-csms"),
        ):
            with self.subTest(node=node, repo=repo), self.assertRaises(PermissionError):
                validate_deployment(repo, node)

    def test_revision_is_fixed_ref_or_exact_sha(self):
        self.assertEqual(
            validate_deployment("arthexis/ocpp-reports", "ocpp-abb-1", "a" * 40)["revision"],
            "a" * 40,
        )
        for ref in ("feature/x", "HEAD~1", "main; echo unsafe", "", "a" * 39):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                validate_deployment("arthexis/ocpp-reports", "ocpp-abb-1", ref)

    def test_malformed_inputs_rejected(self):
        for repo, node in (("../repo", "gway-001"), ("arthexis/ocpp-reports", "bad_name")):
            with self.assertRaises(ValueError):
                validate_deployment(repo, node)


if __name__ == "__main__":
    unittest.main()
