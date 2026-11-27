"""Controller status and real archive compatibility in disposable files only."""
import hashlib
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipapp
import zipfile

from gway_remote.controller_release import (
    controller_evidence, record_verified_deployment, verified_noop, verify_source_package,
)
from gway_remote.mobile_deployments import overview

REPO = Path(__file__).resolve().parents[2]


class ControllerEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.executable = self.root / "gway-remote"
        self.executable.write_bytes(b"installed executable")
        self.executable.chmod(0o755)
        self.digest = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        self.receipt = self.root / "controller-deployment.json"
        self.record = {"schema": 1, "source_sha": "a" * 40,
                       "executable_sha256": self.digest,
                       "verified_at": "2026-01-01T00:00:00+00:00"}
        self.write(self.record)

    def write(self, record):
        self.receipt.write_text(json.dumps(record))
        self.receipt.chmod(0o644)

    def read(self, running="fixture", uid=None):
        return controller_evidence(receipt=self.receipt, executable=self.executable,
                                   running_digest=self.digest if running == "fixture" else running,
                                   uid=os.getuid() if uid is None else uid)

    def test_verified_fields_and_mobile_contract(self):
        with patch("gway_remote.mobile_deployments.export_targets", return_value={"targets": []}):
            value = overview({}, attempts_reader=lambda: {}, revision_reader=lambda _: None,
                             controller_reader=self.read)
        self.assertEqual(value["controller"], {"name": "gway-remote", "installed_sha": "a" * 40,
            "last_successful_update": self.record["verified_at"], "evidence": "verified"})
        self.assertEqual(value["schema"], 1)
        self.assertFalse(value["dispatch_enabled"])

    def test_missing_corrupt_and_untrusted_evidence(self):
        self.receipt.unlink()
        self.assertEqual(self.read()["evidence"], "unavailable")
        self.receipt.write_text("{")
        self.assertEqual(self.read()["evidence"], "unavailable")
        self.write(self.record)
        self.receipt.chmod(0o666)
        self.assertEqual(self.read()["evidence"], "unavailable")
        self.receipt.chmod(0o644)
        self.assertEqual(self.read(uid=os.getuid() + 1)["evidence"], "unavailable")
        other = self.root / "other"
        self.receipt.rename(other)
        self.receipt.symlink_to(other)
        self.assertEqual(self.read()["evidence"], "unavailable")

    def test_stale_running_or_installed_archive(self):
        self.assertEqual(self.read(None)["evidence"], "unavailable")
        self.assertEqual(self.read("b" * 64)["evidence"], "unavailable")
        self.executable.write_bytes(b"replacement executable")
        self.assertIsNone(self.read()["installed_sha"])
        self.assertIsNone(self.read()["last_successful_update"])

    def test_invalid_revision_and_timestamps(self):
        for field, value in (("source_sha", "latest"), ("schema", True),
                             ("verified_at", "2026-01-01T00:00:00"),
                             ("verified_at", (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()),
                             ("executable_sha256", "b" * 64)):
            with self.subTest(field=field, value=value):
                self.write({**self.record, field: value})
                self.assertEqual(self.read()["evidence"], "unavailable")


class ControllerArchiveTests(unittest.TestCase):
    """Use the repository's real committed package installer and zipapp layout.

    Never execute the archive or real privileged commands. The temporary
    installer root and expected UID are explicit test seams.
    """
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.uid = os.getuid()
        self.revision = subprocess.check_output(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip()
        install = runpy.run_path(str(REPO / "scripts/install-package-archive.py"))["install"]
        self.assertTrue(install(REPO, self.root, expected_uid=self.uid)["changed"])
        package = self.root / "zip-source"
        shutil.copytree(self.root / "gway_remote", package / "gway_remote")
        (package / "__main__.py").write_text("from gway_remote.__main__ import main\nmain()\n")
        self.executable = self.root / "gway-remote"
        zipapp.create_archive(package, self.executable, interpreter="/usr/bin/env python3")
        self.executable.chmod(0o755)
        self.digest = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        self.receipt = self.root / "controller-deployment.json"
        self.kw = dict(root=self.root, executable=self.executable, uid=self.uid)
        self.commands = []

    def execute(self, *args):
        self.commands.append(args)
        self.assertEqual(args[:2], ("sudo", "-n"))
        target = Path(args[-1])
        self.assertEqual(target.parent, self.root)
        if args[2] == "install":
            self.assertEqual(args[3:9], ("-o", "root", "-g", "root", "-m", "0644"))
            shutil.copyfile(args[-2], target)
            target.chmod(0o644)
        elif args[2] == "mv":
            self.assertEqual(args[3:5], ("-T", "--"))
            self.assertEqual(Path(args[-2]).parent, self.root)
            os.replace(args[-2], target)
        elif args[2] == "rm":
            self.assertEqual(args[3:5], ("-f", "--"))
            target.unlink(missing_ok=True)
        else:
            self.fail("unexpected command")

    def write_receipt(self, execute=None):
        record_verified_deployment(REPO, self.revision, self.digest,
                                   execute=execute or self.execute, **self.kw)

    def read(self, digest=None):
        return controller_evidence(receipt=self.receipt, executable=self.executable,
                                   running_digest=digest or self.digest, uid=self.uid)

    def test_real_archive_success_atomic_receipt_and_noop(self):
        verify_source_package(REPO, self.revision, self.digest, **self.kw)
        self.assertFalse(verified_noop(REPO, self.revision, **self.kw))
        self.write_receipt()
        self.assertEqual(self.read()["installed_sha"], self.revision)
        self.assertTrue(verified_noop(REPO, self.revision, **self.kw))
        self.assertEqual(self.receipt.stat().st_uid, self.uid)
        self.assertEqual(self.receipt.stat().st_mode & 0o777, 0o644)
        self.assertEqual([args[2] for args in self.commands], ["install", "mv"])
        previous = self.receipt.read_bytes()
        self.write_receipt()
        self.assertEqual(self.receipt.read_bytes(), previous)
        self.assertEqual(len(self.commands), 2)
        self.assertFalse(list(self.root.glob(".controller-deployment-*")))

    def test_tampered_or_rolled_back_zipapp_does_not_skip(self):
        self.write_receipt()
        with zipfile.ZipFile(self.executable, "a") as archive:
            archive.writestr("unexpected.py", "raise RuntimeError()")
        changed = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        self.assertFalse(verified_noop(REPO, self.revision, **self.kw))
        self.assertIsNone(self.read()["installed_sha"])
        with self.assertRaises(ValueError):
            verify_source_package(REPO, self.revision, changed, **self.kw)
        with self.assertRaises(ValueError):
            verify_source_package(REPO, "0" * 40, changed, **self.kw)

    def test_failed_rename_preserves_old_receipt_and_removes_stage(self):
        old = b'{"old":true}'
        self.receipt.write_bytes(old)
        def broken(*args):
            if args[2] == "mv":
                self.assertEqual(self.receipt.read_bytes(), old)
                raise subprocess.CalledProcessError(1, args)
            self.execute(*args)
        with self.assertRaises(subprocess.CalledProcessError):
            self.write_receipt(broken)
        self.assertEqual(self.receipt.read_bytes(), old)
        self.assertFalse(list(self.root.glob(".controller-deployment-*")))

    def test_ambiguous_successful_rename_reconciles_exact_readback(self):
        def ambiguous(*args):
            self.execute(*args)
            if args[2] == "mv":
                raise subprocess.CalledProcessError(1, args)
        self.write_receipt(ambiguous)
        self.assertEqual(self.read()["installed_sha"], self.revision)
        self.assertFalse(list(self.root.glob(".controller-deployment-*")))

    def test_unprotected_stage_is_never_published(self):
        def insecure(*args):
            self.execute(*args)
            if args[2] == "install":
                Path(args[-1]).chmod(0o666)
        with self.assertRaises(ValueError):
            self.write_receipt(insecure)
        self.assertFalse(self.receipt.exists())
        self.assertFalse(list(self.root.glob(".controller-deployment-*")))
        self.assertNotIn("mv", [args[2] for args in self.commands])


if __name__ == "__main__":
    unittest.main()
