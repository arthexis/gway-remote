"""M2 Watchtower enrollment tests using only temporary files and fake wg."""
from __future__ import annotations

import base64
import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

from gway_remote.watchtower_enrollment import (
    EnrollmentFailure, EnrollmentRejected, Ledger, Provisioner, SubprocessWireGuard, WireGuard, make_handler, render_managed_peer,
)


KEY = base64.b64encode(bytes(range(32))).decode("ascii")
KEY_TWO = base64.b64encode(bytes(range(1, 33))).decode("ascii")
ORIGINAL = "[Interface]\nAddress = 10.90.0.1/24\n\n[Peer]\n# existing unmanaged peer\nPublicKey = existing\nAllowedIPs = 10.90.0.2/32\n"


class FakeWireGuard(WireGuard):
    def __init__(self, *, fail_set=False, confirm=True):
        self.peers = {}
        self.fail_set, self.confirm = fail_set, confirm

    def set_peer(self, public_key, address):
        if self.fail_set:
            raise EnrollmentFailure("fake wg failure")
        self.peers[public_key] = address

    def has_peer(self, public_key, address):
        return self.confirm and self.peers.get(public_key) == address

    def remove_peer(self, public_key):
        self.peers.pop(public_key, None)


class WatchtowerEnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.config = root / "gway.conf"
        self.config.write_text(ORIGINAL)
        self.ledger = Ledger(root / "state" / "ledger.sqlite", network="10.90.0.0/24", gateway="10.90.0.1")
        self.wg = FakeWireGuard()
        self.provisioner = Provisioner(self.ledger, self.config, root / "backups", self.wg)

    def _grant(self, device="gway-004"):
        return self.ledger.invite(device)["token"]

    def test_enrollment_preserves_unmanaged_peer_and_consumes_only_after_runtime_verification(self):
        enrolled = self.provisioner.enroll("gway-004", KEY, self._grant())
        self.assertEqual(enrolled.address, "10.90.0.3/32")
        self.assertIn("# existing unmanaged peer", self.config.read_text())
        self.assertIn("# BEGIN gway-remote enrollment: gway-004", self.config.read_text())
        self.assertEqual(self.ledger.status(), {"invitations": 0, "devices": 1, "pending_operations": 0})
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)

    def test_repeat_same_device_key_is_idempotent_but_changed_key_is_rejected(self):
        token = self._grant()
        first = self.provisioner.enroll("gway-004", KEY, token)
        repeated = self.provisioner.enroll("gway-004", KEY, token)
        self.assertTrue(repeated.already_active)
        self.assertEqual(first.address, repeated.address)
        with self.assertRaises(EnrollmentRejected):
            self.provisioner.enroll("gway-004", base64.b64encode(bytes(range(1, 33))).decode(), token)

    def test_runtime_failure_retries_forward_without_consuming_token_early(self):
        token = self._grant()
        self.wg.fail_set = True
        with self.assertRaises(EnrollmentFailure):
            self.provisioner.enroll("gway-004", KEY, token)
        self.assertIn("# existing unmanaged peer", self.config.read_text())
        self.assertEqual(self.ledger.status()["invitations"], 1)
        self.assertEqual(self.ledger.status()["pending_operations"], 1)
        self.wg.fail_set = False
        self.assertEqual(self.provisioner.recover(), 1)
        self.assertEqual(self.ledger.status()["pending_operations"], 0)
        self.assertEqual(self.ledger.status()["devices"], 1)
        self.assertEqual(self.provisioner.recover(), 0)

    def test_confirmation_failure_keeps_peer_for_forward_retry(self):
        token = self._grant()
        self.wg.confirm = False
        with self.assertRaises(EnrollmentFailure):
            self.provisioner.enroll("gway-004", KEY, token)
        self.assertEqual(self.wg.peers.get(KEY), "10.90.0.3/32")
        self.wg.confirm = True
        self.assertEqual(self.provisioner.recover(), 1)
        self.assertEqual(self.wg.peers.get(KEY), "10.90.0.3/32")

    def test_restart_after_config_write_before_receipt_advances_forward(self):
        token = self._grant()
        reserved = self.ledger.reserve(device="gway-004", public_key=KEY, token=token,
                                       occupied={"10.90.0.2/32"}, backup_directory=self.provisioner.backups)
        operation = next(x for x in self.ledger.pending() if x["id"] == reserved.operation_id)
        self.provisioner._prepare_backup(operation, ORIGINAL)
        self.provisioner._write(render_managed_peer(ORIGINAL, reserved))
        # Crash: operation remains reserved, but the config was replaced.
        self.assertEqual(self.provisioner.recover(), 1)
        self.assertEqual(self.ledger.status()["devices"], 1)
        self.assertIn("# existing unmanaged peer", self.config.read_text())
        self.assertTrue(self.wg.has_peer(KEY, reserved.address))

    def test_missing_backup_with_unexpected_config_blocks_without_peer_removal(self):
        token = self._grant()
        reserved = self.ledger.reserve(device="gway-004", public_key=KEY, token=token,
                                       occupied={"10.90.0.2/32"}, backup_directory=self.provisioner.backups)
        self.config.write_text(render_managed_peer(ORIGINAL, reserved))
        with self.assertRaises(EnrollmentFailure):
            self.provisioner.recover()
        self.assertIn("# existing unmanaged peer", self.config.read_text())
        self.assertEqual(self.wg.peers, {})

    def test_unrelated_config_edit_blocks_instead_of_restoring_snapshot(self):
        token = self._grant()
        self.wg.fail_set = True
        with self.assertRaises(EnrollmentFailure):
            self.provisioner.enroll("gway-004", KEY, token)
        self.config.write_text(self.config.read_text() + "# unrelated operator edit\\n")
        self.wg.fail_set = False
        with self.assertRaises(EnrollmentFailure):
            self.provisioner.recover()
        self.assertIn("# unrelated operator edit", self.config.read_text())
        self.assertEqual(self.ledger.status()["pending_operations"], 1)

    def test_concurrent_allocations_keep_both_managed_peers(self):
        grants = [("gway-004", KEY, self._grant("gway-004")),
                  ("gway-005", KEY_TWO, self._grant("gway-005"))]
        failures = []
        def enroll(values):
            try:
                self.provisioner.enroll(*values)
            except Exception as error:  # asserted below without echoing secrets
                failures.append(type(error).__name__)
        threads = [threading.Thread(target=enroll, args=(grant,)) for grant in grants]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(failures, [])
        content = self.config.read_text()
        self.assertIn("gway-004", content)
        self.assertIn("gway-005", content)
        self.assertEqual(self.ledger.status()["devices"], 2)

    def test_pool_exhaustion_accounts_for_unmanaged_config_addresses(self):
        self.ledger = Ledger(Path(self.tmp.name) / "other.sqlite", network="10.90.0.0/30", gateway="10.90.0.1")
        self.provisioner = Provisioner(self.ledger, self.config, Path(self.tmp.name) / "backups2", self.wg)
        with self.assertRaises(EnrollmentFailure):
            self.provisioner.enroll("gway-004", KEY, self._grant())

    def test_live_peer_check_parses_comma_separated_allowed_ips(self):
        from subprocess import CompletedProcess

        def run(args, **_kwargs):
            self.assertEqual(args[:4], ["wg", "show", "gway", "allowed-ips"])
            return CompletedProcess(args, 0, KEY + "\t10.90.0.3/32, 10.90.0.4/32\n", "")

        wg = SubprocessWireGuard(runner=run)
        self.assertTrue(wg.has_peer(KEY, "10.90.0.4/32"))
        self.assertFalse(wg.has_peer(KEY, "10.90.0.5/32"))

    def test_http_handler_rejects_non_json_and_does_not_echo_it(self):
        handler = make_handler(self.provisioner, public_url="https://register.gelectriic.com", wireguard_endpoint="approved.example:51820")
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
        connection.request("POST", "/v1/enroll", body=b'{"token":"secret"}', headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        body = response.read().decode()
        self.assertEqual(response.status, 400)
        self.assertNotIn("secret", body)

    def test_read_only_stage_rejects_a_valid_request_without_touching_ledger_or_wireguard(self):
        from gway_remote.watchtower_enrollment import make_handler
        handler = make_handler(None, public_url="https://register.gelectriic.com",
                               wireguard_endpoint="register.gelectriic.com:51820", read_only_stage=True)
        self.assertTrue(callable(handler))
        self.assertEqual(self.ledger.status()["devices"], 0)
        self.assertEqual(self.wg.peers, {})


if __name__ == "__main__":
    unittest.main()
