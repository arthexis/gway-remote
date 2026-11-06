"""Source-adapter regression tests without network or production dependencies."""
import unittest

from gway_remote.workspace_inspect import github_evidence, deployment_evidence


SHA = "a" * 40


class FakeGitHub:
    def get(self, path):
        if path.endswith("/branches/main"):
            return {"commit": {"sha": SHA}}
        if path.endswith("/commits/" + SHA + "/pulls"):
            return []
        raise AssertionError(path)


class WorkspaceSourceTests(unittest.TestCase):
    def test_missing_sources_are_unknown(self):
        self.assertEqual(github_evidence("owner/repo", None)["state"], "unknown")
        self.assertEqual(deployment_evidence("owner/repo", None)["state"], "unknown")

    def test_github_main_known_but_ci_unverified(self):
        result = github_evidence("owner/repo", FakeGitHub())
        self.assertEqual(result["main_sha"], SHA)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["state"], "unknown")

    def test_github_errors_are_sanitized(self):
        class Failing:
            def get(self, path):
                raise OSError("token should not be shown")
        result = github_evidence("owner/repo", Failing())
        self.assertNotIn("token", str(result))

    def test_unverified_deployment_is_unknown(self):
        receipt = {"repository": "owner/repo", "installation_state": "activated",
                   "activated_revision": SHA, "evidence": []}
        self.assertEqual(deployment_evidence("owner/repo", receipt)["state"], "unknown")

    def test_verified_deployment(self):
        receipt = {"repository": "owner/repo", "installation_state": "activated",
                   "activated_revision": SHA, "evidence": ["verified_active_release"],
                   "runtime_state": "unknown", "observed_at": "2026-11-06T00:00:00Z"}
        result = deployment_evidence("owner/repo", receipt)
        self.assertEqual(result["installed_sha"], SHA)
        self.assertEqual(result["state"], "observed")

    def test_cross_repo_receipt_rejected(self):
        receipt = {"repository": "owner/other", "installation_state": "activated",
                   "activated_revision": SHA, "evidence": ["verified_active_release"]}
        self.assertEqual(deployment_evidence("owner/repo", receipt)["state"], "unknown")


if __name__ == "__main__":
    unittest.main()
