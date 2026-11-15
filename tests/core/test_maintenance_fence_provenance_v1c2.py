"""Hermetic V1-C2 tests; no GitHub/node/deployment access."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from gway_remote.maintenance_fence_provenance import (
    BootSample, ProvenanceError, sample_local_boot, validate_claimed_binding,
    validate_recovery_record)
from gway_remote.maintenance_fence_storage_policy import (
    StoragePolicyError, audit_private_sqlite)

NODE = "gway-001"
BOOT = "boot-alpha-0001"
RESOURCE = "node/gway-001/deploy/ocpp-simulator"
CLAIM = dict(node=NODE, repo="arthexis/ocpp-simulator", sha="a"*40,
             verified_principal="b"*24, source="schedule", request_id="c"*32,
             boot_id=BOOT, lease_until_ns=1000)


def trusted(**kwargs):
    args = dict(trusted_principal="b"*24, trusted_node=NODE,
                trusted_repo="arthexis/ocpp-simulator", trusted_sha="a"*40,
                trusted_source="schedule", trusted_request_id="c"*32,
                trusted_resources=(RESOURCE,), trusted_sample=BootSample(BOOT, 100))
    args.update(kwargs)
    return args


class ProvenanceTests(unittest.TestCase):
    def test_exact_binding_digest_stable(self):
        a = validate_claimed_binding(dict(CLAIM), **trusted())
        self.assertEqual(len(a), 64)
        self.assertEqual(a, validate_claimed_binding(dict(CLAIM), **trusted()))

    def test_every_independent_identity_field_rejected(self):
        variants = [
            {"trusted_principal": "d"*24},
            {"trusted_node": "gway-002"},
            {"trusted_repo": "arthexis/ocpp-csms"},
            {"trusted_sha": "f"*40},
            {"trusted_source": "manual"},
            {"trusted_request_id": "e"*32},
            {"trusted_sample": BootSample("boot-beta-0001", 100)},
            {"trusted_sample": BootSample(BOOT, 1000)},
            {"trusted_resources": ("node/gway-002",)},
        ]
        for changed in variants:
            with self.subTest(changed=changed), self.assertRaises(ProvenanceError):
                validate_claimed_binding(dict(CLAIM), **trusted(**changed))

    def test_payload_identity_and_argument_mutations_denied(self):
        for key, value in (("verified_principal", "d"*24), ("node", "gway-002"),
                           ("request_id", "e"*32), ("lease_until_ns", 90),
                           ("boot_id", "boot-beta-0001"), ("sha", "f"*40)):
            with self.subTest(key=key), self.assertRaises(ProvenanceError):
                validate_claimed_binding({**CLAIM, key: value}, **trusted())
        with self.assertRaises(ProvenanceError):
            validate_claimed_binding({**CLAIM, "unexpected": 1}, **trusted())
        with self.assertRaises(ProvenanceError):
            validate_claimed_binding(dict(CLAIM), **trusted(trusted_resources=[]))

    def test_clock_two_boot_reads_with_monotonic_bracketing(self):
        times = iter((100, 101, 102))
        ids = iter((BOOT, BOOT))
        self.assertEqual(sample_local_boot(read_boot=lambda: next(ids),
                                           monotonic_ns=lambda: next(times)),
                         BootSample(BOOT, 101))

    def test_clock_rollbacks_reboots_stale_missing_and_invalid(self):
        examples = [
            ((100, 99, 101), (BOOT, BOOT)),
            ((100, 101, 2000000200), (BOOT, BOOT)),
            ((100, 101, 102), (BOOT, "boot-beta-0001")),
            ((100, 101, 102), ("", "")),
            ((100, True, 102), (BOOT, BOOT)),
            ((100, 101, 102), (BOOT, BOOT)),
        ]
        for i, (numbers, ids) in enumerate(examples):
            with self.subTest(i=i), self.assertRaises(ProvenanceError):
                t = iter(numbers)
                b = iter(ids)
                if i == len(examples)-1:
                    def broken():
                        raise OSError("not available")
                    sample_local_boot(read_boot=broken, monotonic_ns=lambda: next(t))
                else:
                    sample_local_boot(read_boot=lambda: next(b),
                                      monotonic_ns=lambda: next(t))

    def test_recovery_metadata_requires_independent_matches(self):
        record = dict(request_id="c"*32, node=NODE, admin="d"*24,
                      receipt_digest="e"*64, evidence_digest="f"*64)
        good = dict(trusted_admin="d"*24, trusted_node=NODE,
                    trusted_receipt_digest="e"*64, trusted_evidence_digest="f"*64)
        self.assertEqual(len(validate_recovery_record(record, **good)), 64)
        for change in ({"trusted_admin": "b"*24}, {"trusted_node": "gway-002"},
                       {"trusted_receipt_digest": "0"*64},
                       {"trusted_evidence_digest": "0"*64}):
            with self.subTest(change=change), self.assertRaises(ProvenanceError):
                validate_recovery_record(record, **{**good, **change})
        with self.assertRaises(ProvenanceError):
            validate_recovery_record({**record, "quiescent": True}, **good)


class StoragePolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.db = self.root / "fence.sqlite"
        self.db.write_bytes(b"offline-fixture")
        self.db.chmod(0o600)

    def test_valid_database_and_private_wal_and_shm(self):
        report = audit_private_sqlite(self.root, "fence.sqlite")
        self.assertEqual(report.checked_files, ("fence.sqlite",))
        self.assertEqual(report.uid, os.geteuid())
        for suffix in ("-wal", "-shm"):
            candidate = Path(str(self.db)+suffix)
            candidate.write_bytes(b"sqlite-sidecar")
            candidate.chmod(0o600)
        self.assertEqual(audit_private_sqlite(self.root, "fence.sqlite").checked_files,
                         ("fence.sqlite", "fence.sqlite-wal", "fence.sqlite-shm"))

    def test_symlink_db_and_sidecar_rejected(self):
        self.db.unlink()
        self.db.symlink_to(self.root / "absent")
        with self.assertRaises(StoragePolicyError):
            audit_private_sqlite(self.root, "fence.sqlite")
        self.db.unlink()
        self.db.write_bytes(b"fixture")
        self.db.chmod(0o600)
        Path(str(self.db)+"-wal").symlink_to(self.db)
        with self.assertRaises(StoragePolicyError):
            audit_private_sqlite(self.root, "fence.sqlite")

    def test_symlink_parent_rejected(self):
        link = self.root.parent / (self.root.name + "-link")
        link.symlink_to(self.root, target_is_directory=True)
        self.addCleanup(link.unlink)
        with self.assertRaises(StoragePolicyError):
            audit_private_sqlite(link, "fence.sqlite")

    def test_mode_permissions_and_hardlinks_denied(self):
        self.db.chmod(0o644)
        with self.assertRaises(StoragePolicyError):
            audit_private_sqlite(self.root, "fence.sqlite")
        self.db.chmod(0o600)
        self.root.chmod(0o755)
        with self.assertRaises(StoragePolicyError):
            audit_private_sqlite(self.root, "fence.sqlite")
        self.root.chmod(0o700)
        duplicate = self.root / "another"
        os.link(self.db, duplicate)
        with self.assertRaises(StoragePolicyError):
            audit_private_sqlite(self.root, "fence.sqlite")

    def test_non_file_and_missing_rejected(self):
        self.db.unlink()
        with self.assertRaises(StoragePolicyError):
            audit_private_sqlite(self.root, "fence.sqlite")
        self.db.mkdir()
        with self.assertRaises(StoragePolicyError):
            audit_private_sqlite(self.root, "fence.sqlite")

    def test_bad_name_and_path_rejected(self):
        for filename in ("../fence.sqlite", ".fence.sqlite",
                         "fence.db", "fence.sqlite/anything"):
            with self.subTest(filename=filename), self.assertRaises(StoragePolicyError):
                audit_private_sqlite(self.root, filename)
        with self.assertRaises(StoragePolicyError):
            audit_private_sqlite("relative/path", "fence.sqlite")

    def test_swapped_inode_detected(self):
        real_stat = os.stat
        def mismatch(path, *args, **kwargs):
            info = real_stat(path, *args, **kwargs)
            if path == "fence.sqlite" and kwargs.get("dir_fd") is not None:
                fake = list(info)
                fake[1] += 1
                return os.stat_result(fake)
            return info
        with mock.patch(
            "gway_remote.maintenance_fence_storage_policy.os.stat",
            side_effect=mismatch):
            with self.assertRaises(StoragePolicyError):
                audit_private_sqlite(self.root, "fence.sqlite")


if __name__ == "__main__":
    unittest.main()
