"""Unit tests for asynchronous manual deployment admission and deduplication."""
import concurrent.futures
import os
from pathlib import Path
import tempfile
import unittest

from gway_remote.manual_deploy_async import AsyncDeployBroker
from gway_remote.manual_deploy_broker import DeploymentReceipts

SHA = "a" * 40
INVENTORY = {"nodes": [{"node": "gway-001", "registered": True,
                        "identity_verified": True, "reachable": "reachable"}]}


class AsyncBrokerTests(unittest.TestCase):
    def test_dispatch_dedup_and_status(self):
        with tempfile.TemporaryDirectory() as folder:
            os.chmod(folder, 0o700)
            ledger = DeploymentReceipts(Path(folder) / "jobs.sqlite3")
            calls = []
            def execute(repo, node, sha):
                calls.append((repo, node, sha))
                return {"state": "succeeded"}
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                broker = AsyncDeployBroker(ledger, inventory=lambda: INVENTORY,
                    resolver=lambda *_: SHA, executor=execute, pool=pool)
                args = dict(principal="operator", request_id="a" * 32,
                    repository="arthexis/ocpp-reports", node="gway-001")
                broker.deploy(**args)
                pool.shutdown(wait=True)
                self.assertEqual(broker.deploy(**args)["state"], "succeeded")
                self.assertEqual(len(calls), 1)
                self.assertEqual(broker.status(principal="operator",
                    request_id="a" * 32)["state"], "succeeded")
                with self.assertRaises(PermissionError):
                    broker.status(principal="other", request_id="a" * 32)
                with self.assertRaises(PermissionError):
                    broker.deploy(**{**args, "node": "ocpp-abb-1"})

    def test_denied_node_never_dispatches(self):
        with tempfile.TemporaryDirectory() as folder:
            os.chmod(folder, 0o700)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                broker = AsyncDeployBroker(DeploymentReceipts(Path(folder) / "jobs.sqlite3"),
                    inventory=lambda: {"nodes": []}, resolver=lambda *_: SHA,
                    executor=lambda *_: self.fail("executed denied job"), pool=pool)
                with self.assertRaises(PermissionError):
                    broker.deploy(principal="operator", request_id="b" * 32,
                        repository="arthexis/ocpp-reports", node="gway-001")
