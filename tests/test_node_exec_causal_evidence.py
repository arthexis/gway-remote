"""Negative regression tests for typed worker readiness evidence."""
import json
import unittest
from unittest.mock import patch

from gway_remote.node_exec_protocol import serve_one


class WorkerReadinessEvidenceTests(unittest.TestCase):
    def test_only_proven_user_manager_failure_is_typed(self):
        class Jobs:
            def submit(self, *args, **kwargs):
                raise RuntimeError("executor user manager unavailable")

        payload = {"operation": "submit", "node": "gway-001",
                   "request_id": "a" * 32, "command": "true"}
        with patch("gway_remote.node_exec_protocol.require_account"), \
             patch("gway_remote.node_exec_protocol.validate_command"):
            response = serve_one(json.dumps(payload).encode(), jobs=Jobs(),
                                 hostname="gway-001")
        self.assertEqual(response, {"node": "gway-001", "request_id": "a" * 32,
                                    "status": "rejected",
                                    "failure_stage": "worker_readiness"})

    def test_unrelated_runtime_failure_remains_generic(self):
        class Jobs:
            def submit(self, *args, **kwargs):
                raise RuntimeError("sensitive internal detail")

        payload = {"operation": "submit", "node": "gway-001",
                   "request_id": "a" * 32, "command": "true"}
        with patch("gway_remote.node_exec_protocol.require_account"), \
             patch("gway_remote.node_exec_protocol.validate_command"):
            with self.assertRaises(RuntimeError):
                serve_one(json.dumps(payload).encode(), jobs=Jobs(),
                          hostname="gway-001")


if __name__ == "__main__":
    unittest.main()
