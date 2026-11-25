"""Repeat-run volume checks; mocks never allocate or mount a real device."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch, MagicMock
import stat

spec = importlib.util.spec_from_file_location("feed_volume",
    Path(__file__).resolve().parents[2]/"scripts/provision-watchtower-feed-volume.py")
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)

def info(*, blocks=None, mode=0o600, uid=0, links=1, size=None, ino=42, dev=7):
    return SimpleNamespace(st_mode=stat.S_IFREG|mode, st_uid=uid, st_nlink=links,
        st_size=v.SIZE if size is None else size, st_blocks=v.SIZE//512 if blocks is None else blocks,
        st_ino=ino, st_dev=dev)

class VolumeRegression(TestCase):
    def test_metadata_checks_remain_strict(self):
        for bad in (info(mode=0o644), info(uid=1), info(links=2), info(size=1)):
            with self.assertRaises(PermissionError): v.image_identity(bad)
        self.assertEqual(v.image_identity(info(blocks=1)).st_blocks,1)

    def test_mounted_identity_and_geometry(self):
        before=info(blocks=4)
        with patch.object(v.Path,"lstat",return_value=before), \
             patch.object(v.os.path,"ismount",return_value=True), \
             patch.object(v.Path,"read_text",return_value=str(v.IMAGE)), \
             patch.object(v.os,"statvfs",return_value=SimpleNamespace(f_blocks=100000,f_frsize=4096)):
            for wrong in ("43 0 0","42 4096 0","42 0 1024"):
                with patch.object(v.subprocess,"check_output",side_effect=["/dev/loop5 ext4 rw,nodev,nosuid,noexec",wrong]):
                    with self.assertRaises(PermissionError): v.verify_mount(require_allocation=False)
            with patch.object(v.subprocess,"check_output",side_effect=["/dev/loop5 ext4 rw,nodev,nosuid,noexec","42 0 0"]):
                self.assertIs(v.verify_mount(require_allocation=False),before)

    def test_full_reservation_is_noop(self):
        with patch.object(v,"verify_mount",return_value=info()) as verify, patch.object(v.os,"open") as op:
            self.assertFalse(v.restore_reservation())
            verify.assert_called_once_with(require_allocation=False)
            op.assert_not_called()

    def test_mounted_trim_recovery_preserves_geometry(self):
        sparse=info(blocks=1)
        full=info()
        with patch.object(v,"verify_mount",side_effect=[sparse,full]), \
             patch.object(v.os,"open",return_value=13), \
             patch.object(v.os,"fstat",side_effect=[sparse,full]), \
             patch.object(v.os,"fstatvfs",return_value=SimpleNamespace(f_bavail=1024*1024,f_frsize=4096)), \
             patch.object(v.os,"posix_fallocate") as alloc, \
             patch.object(v.os,"fsync") as sync, patch.object(v.os,"close") as close:
            self.assertTrue(v.restore_reservation())
            alloc.assert_called_once_with(13,0,v.SIZE)
            sync.assert_called_once_with(13)
            close.assert_called_once_with(13)

    def test_low_space_or_changed_inode_never_allocates(self):
        sparse=info(blocks=1)
        for actual in (sparse,info(blocks=1,ino=99)):
            with patch.object(v,"verify_mount",return_value=sparse), \
                 patch.object(v.os,"open",return_value=13), patch.object(v.os,"fstat",return_value=actual), \
                 patch.object(v.os,"fstatvfs",return_value=SimpleNamespace(f_bavail=1,f_frsize=4096)), \
                 patch.object(v.os,"posix_fallocate") as alloc, patch.object(v.os,"close"):
                with self.assertRaises((RuntimeError,PermissionError)): v.restore_reservation()
                alloc.assert_not_called()

    def test_incomplete_reservation_remains_blocked(self):
        sparse=info(blocks=1)
        with patch.object(v,"verify_mount",return_value=sparse), \
             patch.object(v.os,"open",return_value=13), patch.object(v.os,"fstat",return_value=sparse), \
             patch.object(v.os,"fstatvfs",return_value=SimpleNamespace(f_bavail=1024*1024,f_frsize=4096)), \
             patch.object(v.os,"posix_fallocate"), patch.object(v.os,"fsync"),patch.object(v.os,"close"):
            with self.assertRaisesRegex(PermissionError,"could not be restored"): v.restore_reservation()
