import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.public_sound import promote

import importlib.util
import hashlib


def load_helper():
    path = Path("scripts/gway-promote-sound")
    spec = importlib.util.spec_from_file_location("gway_promote_sound", path)
    # Extensionless executable: load it explicitly as Python source.
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader("gway_promote_sound", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


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

    def test_helper_rejects_unpinned_release(self):
        helper = load_helper()
        with self.assertRaisesRegex(ValueError, "Invalid pinned SHA"):
            helper.validated_source("main")

    def test_helper_atomic_promotion_without_restore(self):
        helper = load_helper()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sha = "a" * 40
            release = root / "releases" / sha[:12]
            source = release / "scripts/gway/sound.sh"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"#!/bin/sh\\necho --motif\\n")
            source.chmod(0o755)
            (root / "current").symlink_to(release)
            target = root / "system" / "sound.sh"
            target.parent.mkdir()
            target.write_bytes(b"old")
            alias = root / "sound"
            alias.symlink_to(target)
            with patch.object(helper, "ROOT", root), patch.object(helper, "TARGET", target), \
                 patch.object(helper, "PUBLIC", (alias,)), patch.object(helper.os, "chown"):
                helper.operate("promote:" + sha)
                self.assertEqual(target.read_bytes(), source.read_bytes())
                with self.assertRaisesRegex(ValueError, "Unknown operation"):
                    helper.operate("restore:" + sha)
