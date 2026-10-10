"""Exact revision evidence tests; no production artifact is fabricated."""
import json
import tempfile
import unittest
from pathlib import Path

from gway_remote.revision import artifact_revision, verified_revision


class RevisionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.markers = self.home / "markers"
        self.markers.mkdir()
        self.release = self.home / ".local/share/gway-lcd-sound/releases/abc"
        self.release.mkdir(parents=True)
        current = self.home / ".local/share/gway-lcd-sound/current"
        current.symlink_to(self.release, target_is_directory=True)
        self.sha = "a" * 40

    def write(self, path, sha, component="gway-lcd-sound"):
        path.write_text(json.dumps({"component": component, "sha": sha}))

    def test_missing_artifact_evidence_fails_closed(self):
        self.write(self.markers / "gway-lcd-sound.json", self.sha)
        self.assertIsNone(verified_revision("gway-lcd-sound", self.markers, self.home))

    def test_exact_artifact_and_marker_agreement(self):
        self.write(self.markers / "gway-lcd-sound.json", self.sha)
        self.write(self.release / ".gway-revision.json", self.sha.upper())
        self.assertEqual(verified_revision("gway-lcd-sound", self.markers, self.home), self.sha)

    def test_disagreement_fails_closed(self):
        self.write(self.markers / "gway-lcd-sound.json", self.sha)
        self.write(self.release / ".gway-revision.json", "b" * 40)
        self.assertIsNone(verified_revision("gway-lcd-sound", self.markers, self.home))

    def test_invalid_or_wrong_component_fails_closed(self):
        self.write(self.release / ".gway-revision.json", self.sha, "ocpp-csms")
        self.assertIsNone(artifact_revision("gway-lcd-sound", self.home))
        with self.assertRaises(ValueError):
            artifact_revision("unknown", self.home)


if __name__ == "__main__":
    unittest.main()
