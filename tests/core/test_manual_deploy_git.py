"""No-network regression tests for fixed Git SHA resolution."""
import subprocess
import unittest
from types import SimpleNamespace

from gway_remote.manual_deploy_git import resolve_sha

SHA = "a" * 40


class ManualDeployGitTests(unittest.TestCase):
    def test_main_resolves_with_fixed_url(self):
        calls = []
        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(stdout=SHA + "\trefs/heads/main\n")
        self.assertEqual(resolve_sha("arthexis/ocpp-reports", "main", run=fake_run), SHA)
        self.assertEqual(calls[0][0][3], "https://github.com/arthexis/ocpp-reports.git")
        self.assertEqual(calls[0][1]["timeout"], 15)

    def test_full_sha_needs_no_network(self):
        self.assertEqual(resolve_sha("arthexis/ocpp-reports", SHA,
                                    run=lambda *_a, **_kw: self.fail("network")), SHA)

    def test_rejects_unknown_repo_and_untrusted_refs(self):
        for repository, revision in (
            ("arthexis/unknown", "main"),
            ("arthexis/ocpp-reports", "--upload-pack=sh"),
            ("arthexis/ocpp-reports", "feature/branch"),
        ):
            with self.subTest(repository=repository, revision=revision):
                with self.assertRaises((ValueError, PermissionError)):
                    resolve_sha(repository, revision)

    def test_rejects_ambiguous_or_invalid_remote(self):
        for stdout in ("", SHA + "\trefs/tags/main\n",
                       SHA + "\trefs/heads/main\n" * 2,
                       "not-a-sha\trefs/heads/main\n"):
            with self.subTest(stdout=stdout):
                with self.assertRaises(ValueError):
                    resolve_sha("arthexis/ocpp-reports", "main",
                                run=lambda *_a, **_kw: SimpleNamespace(stdout=stdout))
