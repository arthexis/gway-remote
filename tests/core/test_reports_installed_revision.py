"""Hermetic installed SHA extraction from Reports' immutable packaged releases.

This is release-link evidence, not proof of the bytes currently running in a
service process. No real appliance paths, services or credentials are touched.
"""
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.probe_registry import Probe
from gway_remote.status import installed_revision

SHA = "4a7874377d735571836f3c4b4629220b1ad97e99"
REPORTS_ROOT = Path("/opt/ocpp-reports/releases")
EXE_LINK = Path("/usr/local/bin/ocpp-reports")


class ReportsInstalledRevisionTests(unittest.TestCase):
    def observed(self, resolved, *, name="ocpp-reports", is_link=True, broken=False):
        """Mock only the filesystem boundary, not the revision parser."""
        spec = Probe("executable", executable=str(EXE_LINK),
                     revision_from_executable=True)
        with patch("gway_remote.status.probe_for", return_value=spec), (
                patch.object(Path, "is_symlink", return_value=is_link)), (
                patch.object(Path, "resolve", side_effect=OSError("missing") if broken
                             else lambda *args, **kwargs: Path(resolved))):
            return installed_revision(name)

    def test_reports_packaged_release_is_normalized_to_full_sha(self):
        binary = REPORTS_ROOT / (SHA + "-pkg") / "venv/bin/ocpp-reports"
        self.assertEqual(self.observed(binary), SHA)

    def test_existing_plain_hex_release_behavior_is_preserved(self):
        executable = Path("/home/arthe/.local/share/gway-agent-ops/releases") / SHA / "bin/agent"
        self.assertEqual(self.observed(executable, name="gway-agent-ops"), SHA)

    def test_packaged_suffix_does_not_apply_to_other_providers(self):
        binary = REPORTS_ROOT / (SHA + "-pkg") / "venv/bin/ocpp-reports"
        self.assertIsNone(self.observed(binary, name="gway-agent-ops"))

    def test_packaged_suffix_rejects_untrusted_release_root(self):
        binary = Path("/tmp/operator/releases") / (SHA + "-pkg") / "venv/bin/ocpp-reports"
        self.assertIsNone(self.observed(binary))

    def test_packaged_suffix_requires_exact_binary_in_release(self):
        binary = REPORTS_ROOT / (SHA + "-pkg") / "venv/bin/other"
        self.assertIsNone(self.observed(binary))
        deeper = REPORTS_ROOT / (SHA + "-pkg") / "nested/venv/bin/ocpp-reports"
        self.assertIsNone(self.observed(deeper))

    def test_malformed_packaged_revisions_are_unknown(self):
        for suffix in ("", "-dev", "-pkg-old", "-pkg/", "-pkg.pkg"):
            with self.subTest(suffix=suffix):
                binary = REPORTS_ROOT / (SHA + suffix) / "venv/bin/ocpp-reports"
                if suffix == "":
                    self.assertEqual(self.observed(binary), SHA)
                else:
                    self.assertIsNone(self.observed(binary))
        for invalid in (SHA.upper() + "-pkg", SHA[:-1] + "-pkg",
                        "g" * 40 + "-pkg", "prefix-" + SHA + "-pkg"):
            with self.subTest(invalid=invalid):
                self.assertIsNone(self.observed(REPORTS_ROOT / invalid / "venv/bin/ocpp-reports"))

    def test_missing_link_and_broken_target_fail_closed(self):
        binary = REPORTS_ROOT / (SHA + "-pkg") / "venv/bin/ocpp-reports"
        self.assertIsNone(self.observed(binary, is_link=False))
        self.assertIsNone(self.observed(binary, broken=True))

    def test_unrelated_executable_does_not_gain_new_revision_pattern(self):
        binary = Path("/opt/gway-agent-ops/releases") / (SHA + "-pkg") / "bin/agent"
        self.assertIsNone(self.observed(binary, name="gway-agent-ops"))


if __name__ == "__main__":
    unittest.main()
