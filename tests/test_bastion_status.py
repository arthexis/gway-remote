import json
import tempfile
import unittest
from pathlib import Path

from gway_remote.bastion_status import read_bastion_evidence


SHA = "a" * 40
OTHER = "b" * 40


class BastionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, kind, sha, release=True):
        if release:
            release_dir = self.root / "releases" / sha
            release_dir.mkdir(parents=True, exist_ok=True)
            (release_dir / "REVISION").write_text(sha + "\n")
        dest = self.root / "deployment"
        dest.mkdir(exist_ok=True)
        (dest / (kind + ".json")).write_text(json.dumps({"schema": 1, "revision": sha}))

    def test_missing(self):
        self.assertEqual(read_bastion_evidence(self.root)["release_state"], "unknown")

    def test_staged_only(self):
        self.write("staged", SHA)
        status = read_bastion_evidence(self.root)
        self.assertEqual(status["release_state"], "staged")
        self.assertEqual(status["staged_sha"], SHA)
        self.assertIsNone(status["activated_sha"])
        self.assertEqual(status["runtime"], "not_applicable")

    def test_activated(self):
        self.write("staged", OTHER)
        self.write("activated", SHA)
        status = read_bastion_evidence(self.root)
        self.assertEqual(status["release_state"], "activated")
        self.assertEqual(status["activated_sha"], SHA)
        self.assertEqual(status["runtime"], "unknown")

    def test_malformed(self):
        self.write("staged", SHA, release=False)
        status = read_bastion_evidence(self.root)
        self.assertEqual(status["evidence"], "invalid")
        self.assertIsNone(status["staged_sha"])

    def test_symlink(self):
        self.write("staged", SHA)
        target = self.root / "deployment" / "staged.json"
        target.rename(target.with_suffix(".saved"))
        target.symlink_to(target.with_suffix(".saved"))
        self.assertEqual(read_bastion_evidence(self.root)["evidence"], "invalid")


if __name__ == "__main__":
    unittest.main()
