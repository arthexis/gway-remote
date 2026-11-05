"""Issue 411: missing remote jobs must not crash MCP result retrieval."""
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from gway_remote.watchtower_exec_transport import DormantRelay


class TestUncertainResult(unittest.TestCase):
    def test_rejection_returns_safe_status_without_retry(self):
        ledger = Mock()
        ledger.get.return_value = {
            "node": "gway-001", "host_key_sha256": "a" * 64,
            "state": "uncertain",
        }
        transport = Mock()
        transport.node = SimpleNamespace(node="gway-001", host_key_sha256="a" * 64)
        transport.invoke.side_effect = subprocess.CalledProcessError(
            1, ["ssh", "private"], stderr=b"sensitive remote stderr"
        )
        relay = DormantRelay(ledger, transport, enabled=True)

        result = relay.result("b" * 32)
        self.assertEqual(result, {
            "node": "gway-001", "request_id": "b" * 32,
            "status": "uncertain", "result_available": False,
            "reason": "node_result_unavailable",
        })
        self.assertNotIn("sensitive", str(result))
        self.assertEqual(transport.invoke.call_count, 1)
        self.assertEqual(transport.invoke.call_args.args[0]["operation"], "result")
        ledger.record_result_state.assert_not_called()
        ledger.claim_dispatch.assert_not_called()
