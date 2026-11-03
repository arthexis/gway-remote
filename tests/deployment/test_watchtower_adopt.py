"""No-bootstrap enrollment of already-provisioned WireGuard peers."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from gway_remote.watchtower_adopt import adopt
from gway_remote.watchtower_enrollment import Ledger


# Valid WireGuard key from operator's verified peer, not a credential.
PUB = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


class AdoptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ledger = Ledger(self.root / "ledger.sqlite3", network="10.90.0.0/24",
                             gateway="10.90.0.1")
        self.config = self.root / "gway.conf"
        self.config.write_text("[Interface]\nAddress = 10.90.0.1/24\n\n"
                               "[Peer]\nPublicKey = " + PUB + "\nAllowedIPs = 10.90.0.2/32\n")
        self.calls = []

    def runner(self, argv, **kwargs):
        self.calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=PUB + "\t10.90.0.2/32\n")

    def run_adopt(self, **kw):
        return adopt(self.ledger, node="gway-001", public_key=PUB, config=self.config,
                     runner=self.runner, **kw)

    def test_dry_run_has_no_ledger_writes(self):
        self.assertEqual(self.run_adopt(dry_run=True)["state"], "would_adopt")
        self.assertEqual(self.ledger.status()["devices"], 0)
        self.assertEqual(self.calls, [["wg", "show", "gway", "allowed-ips"]])

    def test_commit_and_idempotency_without_network_mutation(self):
        self.assertEqual(self.run_adopt()["state"], "adopted")
        self.assertEqual(self.run_adopt()["state"], "already_adopted")
        self.assertEqual(self.ledger.status()["devices"], 1)
        snapshot = self.ledger.inspection_snapshot()["nodes"]
        self.assertEqual(snapshot[0]["node"], "gway-001")
        self.assertNotIn("host_identity", snapshot[0])
        self.assertFalse(self.run_adopt()["execute_available"])
        self.assertTrue(all(argv[1:3] == ["show", "gway"] for argv in self.calls))

    def test_wrong_key_or_ambiguous_peer_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "exactly once"):
            adopt(self.ledger, node="gway-001", public_key="BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBA=",
                  config=self.config, runner=self.runner)
        self.config.write_text(self.config.read_text() +
                               "[Peer]\nPublicKey = " + PUB + "\nAllowedIPs = 10.90.0.3/32\n")
        with self.assertRaisesRegex(ValueError, "exactly once"):
            self.run_adopt()
        self.assertEqual(self.ledger.status()["devices"], 0)

    def test_disagreement_between_config_and_runtime_refused(self):
        def wrong(argv, **kw):
            return subprocess.CompletedProcess(argv, 0, stdout=PUB + "\t10.90.0.9/32\n")
        with self.assertRaisesRegex(ValueError, "does not match"):
            adopt(self.ledger, node="gway-001", public_key=PUB, config=self.config, runner=wrong)
        self.assertEqual(self.ledger.status()["devices"], 0)

    def test_conflicting_node_and_address_refused(self):
        self.run_adopt()
        with self.assertRaisesRegex(ValueError, "already registered"):
            adopt(self.ledger, node="gway-007", public_key=PUB, config=self.config,
                  runner=self.runner)
        self.assertEqual(self.ledger.status()["devices"], 1)

    def test_symlink_config_refused(self):
        alias = self.root / "alias"
        alias.symlink_to(self.config)
        with self.assertRaisesRegex(ValueError, "unsafe"):
            adopt(self.ledger, node="gway-001", public_key=PUB, config=alias,
                  runner=self.runner)

    def test_invalid_node_refused(self):
        with self.assertRaisesRegex(ValueError, "invalid node"):
            adopt(self.ledger, node="../../x", public_key=PUB, config=self.config,
                  runner=self.runner)


if __name__ == "__main__":
    unittest.main()
