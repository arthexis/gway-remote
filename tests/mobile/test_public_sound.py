import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.public_sound import promote


class PublicSoundTests(unittest.TestCase):
    def test_rejects_unpinned_revision(self):
        with self.assertRaisesRegex(ValueError, "pinned"):
            promote("main")

    def test_rejects_missing_active_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "Active"):
                promote("a" * 40, release_root=tmp)

    def test_rejects_missing_player_before_sudo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = root / "releases" / ("a" * 12)
            release.mkdir(parents=True)
            (root / "current").symlink_to(release)
            with patch("gway_remote.public_sound.subprocess.run") as run:
                with self.assertRaisesRegex(RuntimeError, "missing"):
                    promote("a" * 40, release_root=root)
                run.assert_not_called()

    def test_promote_rejects_missing_helper_before_sudo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = root / "releases" / ("a" * 12)
            player = release / "scripts/gway/sound.sh"
            player.parent.mkdir(parents=True)
            player.write_text("#!/bin/sh\\necho --motif\\n")
            player.chmod(0o755)
            (root / "current").symlink_to(release)
            with patch("gway_remote.public_sound.HELPER", str(root / "missing")):
                with self.assertRaisesRegex(RuntimeError, "helper is missing"):
                    promote("a" * 40, release_root=root)
