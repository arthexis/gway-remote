"""B2 archive installer: content-addressed, no-op and failure recovery."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/install-package-archive.py"
spec = importlib.util.spec_from_file_location("gway_package_installer", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ArchiveInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        pkg = self.repo / "gway_remote"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "__main__.py").write_text("answer = 1\n")
        (pkg / "node_exec_worker.py").write_text("worker = True\n")
        subprocess.run(["git", "-C", str(self.repo), "init", "-q"], check=True)
        self.commit()
        self.root = self.base / "opt"
        self.root.mkdir()
        self.uid = os.getuid()

    def commit(self):
        subprocess.run(["git", "-C", str(self.repo), "add", "gway_remote"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=test",
                        "-c", "user.email=test@example.invalid",
                        "commit", "-qm", "package"], check=True)

    def install(self, **kwargs):
        return module.install(self.repo, self.root,
                              expected_uid=self.uid, **kwargs)

    def test_first_install_and_repeat_are_idempotent(self):
        initial = self.install()
        self.assertTrue(initial["changed"])
        link = self.root / "gway_remote"
        self.assertTrue(link.is_symlink())
        self.assertEqual((link / "__main__.py").read_text(), "answer = 1\n")
        self.assertFalse(self.install()["changed"])
        self.assertEqual(self.install()["sha256"], initial["sha256"])

    def test_new_release_is_traversable_by_unprivileged_importers(self):
        installed = self.install()
        release = self.root / ".package-releases" / installed["sha256"]
        self.assertEqual(release.stat().st_mode & 0o777, 0o755)
        self.assertEqual((release / "gway_remote").stat().st_mode & 0o777, 0o755)

    def test_existing_private_release_is_repaired_without_new_digest(self):
        installed = self.install()
        release = self.root / ".package-releases" / installed["sha256"]
        release.chmod(0o700)
        fixed = self.install()
        self.assertTrue(fixed["changed"])
        self.assertEqual(fixed["sha256"], installed["sha256"])
        self.assertEqual(release.stat().st_mode & 0o777, 0o755)
        self.assertFalse(self.install()["changed"])

    def test_untracked_pycache_does_not_enter_archive_or_change_digest(self):
        initial = self.install()
        cache = self.repo / "gway_remote/__pycache__"
        cache.mkdir()
        (cache / "node_exec_worker.cpython-311.pyc").write_bytes(b"nonsense")
        (self.repo / "gway_remote/private.txt").write_text("untracked")
        again = self.install()
        self.assertFalse(again["changed"])
        self.assertEqual(again["sha256"], initial["sha256"])
        self.assertFalse((self.root / "gway_remote/__pycache__").exists())
        self.assertFalse((self.root / "gway_remote/private.txt").exists())

    def test_changed_package_switches_pointer_after_validation(self):
        old = self.install()
        (self.repo / "gway_remote/__main__.py").write_text("answer = 2\n")
        self.commit()
        new = self.install()
        self.assertTrue(new["changed"])
        self.assertNotEqual(new["sha256"], old["sha256"])
        self.assertEqual((self.root / "gway_remote/__main__.py").read_text(),
                         "answer = 2\n")
        self.assertEqual((self.root / ".package-releases" / old["sha256"] /
                          "gway_remote/__main__.py").read_text(), "answer = 1\n")

    def test_pre_activation_failure_keeps_current_release(self):
        old = self.install()
        (self.repo / "gway_remote/__main__.py").write_text("answer = 2\n")
        self.commit()
        def failed():
            raise RuntimeError("simulated failure before activation")
        with self.assertRaisesRegex(RuntimeError, "simulated"):
            self.install(before_activate=failed)
        self.assertEqual((self.root / "gway_remote/__main__.py").read_text(),
                         "answer = 1\n")
        self.assertEqual(os.readlink(self.root / "gway_remote"),
                         ".package-releases/" + old["sha256"] + "/gway_remote")

    def test_invalid_python_cannot_be_activated(self):
        self.install()
        (self.repo / "gway_remote/__main__.py").write_text("def broken(:\n")
        self.commit()
        with self.assertRaises(SyntaxError):
            self.install()
        self.assertEqual((self.root / "gway_remote/__main__.py").read_text(),
                         "answer = 1\n")

    def test_legacy_directory_is_preserved_during_migration(self):
        legacy = self.root / "gway_remote"
        legacy.mkdir()
        (legacy / "local").write_text("old content")
        self.assertTrue(self.install()["changed"])
        self.assertEqual((self.root / ".gway_remote.legacy-before-archive" /
                          "local").read_text(), "old content")
        self.assertTrue(legacy.is_symlink())

    def test_unmanaged_symlink_is_rejected(self):
        (self.root / "gway_remote").symlink_to("/etc")
        with self.assertRaisesRegex(ValueError, "unmanaged"):
            self.install()

    def test_role_uses_one_archive_install_and_preserves_cli_gate(self):
        tasks = (ROOT / "ansible/roles/gway_remote/tasks/main.yml").read_text()
        self.assertIn("scripts/install-package-archive.py", tasks)
        self.assertIn("changed_when: (gway_remote_source.stdout | from_json).changed | bool", tasks)
        self.assertNotIn('src: "{{ playbook_dir }}/../gway_remote/"', tasks)
        self.assertIn("gway_remote_source.changed or gway_remote_installer.changed", tasks)


if __name__ == "__main__":
    unittest.main()
