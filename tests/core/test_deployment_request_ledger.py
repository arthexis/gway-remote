"""Deployment request binding shares the existing durable Watchtower ledger."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from gway_remote.watchtower_exec_transport import RequestLedger


class DeploymentLedgerTests(unittest.TestCase):
    def test_durable_dedup_and_conflicting_request_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os.chmod(root, 0o700)
            path = root / "requests.sqlite3"
            args = dict(request_id="a" * 32, node="gway-001", application="sample",
                        revision="main", principal="b" * 24,
                        host_key_sha256="c" * 64,
                        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=3)).isoformat())
            ledger = RequestLedger(path)
            first = ledger.reserve_deployment(**args)
            self.assertEqual(first["state"], "reserved")
            self.assertEqual(RequestLedger(path).reserve_deployment(**args), first)
            with self.assertRaises(ValueError):
                ledger.reserve_deployment(**{**args, "application": "different"})
            self.assertTrue(ledger.claim_dispatch(args["request_id"]))
            self.assertFalse(RequestLedger(path).claim_dispatch(args["request_id"]))

    def test_uncertain_dispatch_reconciles_terminal_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os.chmod(root, 0o700)
            path = root / "requests.sqlite3"
            args = dict(request_id="d"*32, node="gway-001",
                        application="sample", revision="main",
                        principal="b"*24, host_key_sha256="c"*64,
                        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=3)).isoformat())
            ledger = RequestLedger(path)
            ledger.reserve_deployment(**args)
            self.assertTrue(ledger.claim_dispatch(args["request_id"]))
            ledger.mark_dispatched(args["request_id"], confirmed=False)
            self.assertEqual(RequestLedger(path).get(args["request_id"])["state"], "uncertain")
            self.assertFalse(RequestLedger(path).claim_dispatch(args["request_id"]))
            RequestLedger(path).record_result_state(args["request_id"], "succeeded")
            self.assertEqual(ledger.get(args["request_id"])["state"], "succeeded")
            ledger.record_result_state(args["request_id"], "succeeded")
            with self.assertRaises(ValueError):
                ledger.record_result_state(args["request_id"], "failed")
            with self.assertRaises(ValueError):
                ledger.reserve_deployment(**{**args, "principal": "e"*24})

    def test_confirmed_dispatch_terminal_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os.chmod(root, 0o700)
            path = root / "requests.sqlite3"
            args = dict(request_id="e"*32, node="gway-001",
                        application="sample", revision="main",
                        principal="b"*24, host_key_sha256="c"*64,
                        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=3)).isoformat())
            ledger = RequestLedger(path)
            ledger.reserve_deployment(**args)
            self.assertTrue(ledger.claim_dispatch(args["request_id"]))
            ledger.mark_dispatched(args["request_id"], confirmed=True)
            self.assertEqual(RequestLedger(path).get(args["request_id"])["state"], "dispatched")
            self.assertFalse(RequestLedger(path).claim_dispatch(args["request_id"]))
            RequestLedger(path).record_result_state(args["request_id"], "failed")
            self.assertEqual(ledger.get(args["request_id"])["state"], "failed")


if __name__ == "__main__":
    unittest.main()
