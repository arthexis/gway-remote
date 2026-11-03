"""Acceptance tests: explicit attestation and bounded WireGuard reachability."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import base64
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from gway_remote.watchtower_attest import attest
from gway_remote.watchtower_adopt import adopt
from gway_remote.watchtower_enrollment import Ledger
from gway_remote.node_reachability import observe
from gway_remote import node_registry_inventory


WG = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
SSH = "ssh-ed25519 " + base64.b64encode(
    b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + b"\x01" * 32
).decode("ascii")


class AttestAndReachabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ledger = Ledger(self.root / "ledger.sqlite3", network="10.90.0.0/24", gateway="10.90.0.1")
        self.conf = self.root / "gway.conf"
        self.conf.write_text("[Interface]\nAddress=10.90.0.1/24\n[Peer]\nPublicKey=" + WG + "\nAllowedIPs=10.90.0.2/32\n")
        self.key = self.root / "host.pub"
        self.key.write_text(SSH + "\n")
        self.key.chmod(0o600)
        self.runner = lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout=WG + "\t10.90.0.2/32\n")

    def test_attest_after_adoption(self):
        adopt(self.ledger, node="gway-001", public_key=WG, config=self.conf, runner=self.runner)
        with patch("gway_remote.watchtower_attest.trusted_file"):
            self.assertEqual(attest(self.ledger, node="gway-001", host_key_file=self.key, dry_run=True)["state"], "would_attest")
            self.assertFalse(node_registry_inventory.build(self.ledger.path)["nodes"][0]["identity_verified"])
            self.assertEqual(attest(self.ledger, node="gway-001", host_key_file=self.key)["state"], "attested")
            self.assertEqual(attest(self.ledger, node="gway-001", host_key_file=self.key)["state"], "already_attested")
            self.assertTrue(node_registry_inventory.build(self.ledger.path)["nodes"][0]["identity_verified"])

    def test_atomic_adopt_and_attest(self):
        with patch("gway_remote.watchtower_attest.trusted_file"):
            result = adopt(self.ledger, node="gway-001", public_key=WG, config=self.conf,
                           runner=self.runner, host_key_file=self.key)
        self.assertEqual(result["state"], "adopted")
        self.assertEqual(result["attestation"], "attested")
        self.assertTrue(result["identity_verified"])

    def test_failed_attest_rolls_back_adoption(self):
        self.key.write_text("invalid-key\n")
        with patch("gway_remote.watchtower_attest.trusted_file"):
            with self.assertRaises(ValueError):
                adopt(self.ledger, node="gway-001", public_key=WG, config=self.conf,
                      runner=self.runner, host_key_file=self.key)
        self.assertEqual(self.ledger.status()["devices"], 0)

    def test_standard_ssh_host_public_key_comment_is_accepted(self):
        self.key.write_text(SSH + " root@gway-001\\n")
        adopt(self.ledger, node="gway-001", public_key=WG, config=self.conf, runner=self.runner)
        with patch("gway_remote.watchtower_attest.trusted_file"):
            result = attest(self.ledger, node="gway-001", host_key_file=self.key)
        self.assertEqual(result["state"], "attested")

    def test_same_host_key_cannot_attest_to_two_nodes(self):
        adopt(self.ledger, node="gway-001", public_key=WG, config=self.conf, runner=self.runner)
        with patch("gway_remote.watchtower_attest.trusted_file"):
            attest(self.ledger, node="gway-001", host_key_file=self.key)
            with self.ledger._transaction() as db:
                db.execute(
                    "INSERT INTO devices(device,public_key,address,state,operation_id) "
                    "VALUES('gway-002',?,?,'active','manual-fixture')",
                    ("BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBA=", "10.90.0.3/32"),
                )
            with self.assertRaisesRegex(ValueError, "already attested"):
                attest(self.ledger, node="gway-002", host_key_file=self.key)

    def test_attestation_refuses_conflicting_host_key(self):
        with patch("gway_remote.watchtower_attest.trusted_file"):
            adopt(self.ledger, node="gway-001", public_key=WG, config=self.conf,
                  runner=self.runner, host_key_file=self.key)
            self.key.write_text(SSH.replace("AQEBAQE", "AgICAgI"))
            with self.assertRaises(ValueError):
                attest(self.ledger, node="gway-001", host_key_file=self.key)

    def test_recent_handshake_updates_inventory(self):
        adopt(self.ledger, node="gway-001", public_key=WG, config=self.conf, runner=self.runner)
        now = datetime.now(timezone.utc)
        ts = int((now - timedelta(seconds=30)).timestamp())
        runner = lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout=f"{WG}\t{ts}\n")
        observation = observe(self.ledger.path, runner=runner, now=now)
        self.assertEqual(observation["gway-001"]["reachable"], "reachable")
        with patch("gway_remote.node_reachability.observe", return_value=observation):
            row = node_registry_inventory.build(self.ledger.path, probe=True)["nodes"][0]
            self.assertEqual(row["reachable"], "reachable")
            self.assertIsNotNone(row["observed_at"])

    def test_stale_or_failed_handshake_remains_unknown(self):
        adopt(self.ledger, node="gway-001", public_key=WG, config=self.conf, runner=self.runner)
        now = datetime.now(timezone.utc)
        stale = int((now - timedelta(seconds=500)).timestamp())
        runner = lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout=f"{WG}\t{stale}\n")
        self.assertEqual(observe(self.ledger.path, runner=runner, now=now), {})
        failed = lambda argv, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired(argv, 8))
        self.assertEqual(observe(self.ledger.path, runner=failed, now=now), {})


if __name__ == "__main__":
    unittest.main()
