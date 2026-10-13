"""Regression coverage for versioned Agent Ops envelopes and ambiguous submissions."""
import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from gway_remote import agent_ops_adapter as ops


class AgentOpsContractTests(unittest.TestCase):
    def _run(self, command, status="ok", data=None, code=0):
        result = {"schema_version": 1, "command": command, "status": status,
                  "data": {} if data is None else data, "error": None}
        with patch.object(ops, "_agent_path", return_value="/usr/bin/agent"), \
                patch.object(ops.subprocess, "run", return_value=Mock(
                    returncode=code, stdout=json.dumps(result))) as runner:
            if command == "issue":
                output = ops._run(["issue", "owner/repo#1", "--at", "2026-10-13T15:00:00Z"])
            else:
                output = ops._run([command])
        return output, runner.call_args

    def test_read_contract(self):
        data, call = self._run("issues", data={"issues": []})
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(call.kwargs["timeout"], 20)

    def test_finished_issue_contract_has_distinct_timeout(self):
        data, call = self._run("issue", status="finished")
        self.assertEqual(data["status"], "finished")
        self.assertGreater(call.kwargs["timeout"], 20)

    def test_busy_and_duplicate_are_not_success(self):
        for status, expected in [("busy", "agent_busy"), ("duplicate", "agent_duplicate")]:
            payload = {"schema_version": 1, "command": "issue", "status": status,
                       "data": None, "error": {"code": status}}
            with patch.object(ops, "_agent_path", return_value="/usr/bin/agent"), \
                    patch.object(ops.subprocess, "run", return_value=Mock(
                        returncode=4, stdout=json.dumps(payload))):
                with self.subTest(status=status), self.assertRaisesRegex(ops.AgentOpsError, expected):
                    ops._run(["issue", "owner/repo#1", "--at", "2026-10-13T15:00:00Z"])

    def test_contract_fail_closed(self):
        for payload in [{}, [], {"schema_version": 999, "command": "issues", "status": "ok",
                                 "data": {}, "error": None},
                        {"schema_version": 1, "command": "status", "status": "ok",
                         "data": {}, "error": None}]:
            with patch.object(ops, "_agent_path", return_value="/usr/bin/agent"), \
                    patch.object(ops.subprocess, "run", return_value=Mock(
                        returncode=0, stdout=json.dumps(payload))):
                with self.subTest(payload=payload), self.assertRaisesRegex(ops.AgentOpsError, "agent_invalid_contract"):
                    ops._run(["issues"])

    def test_issue_timeout_is_unconfirmed_not_failure_proof(self):
        with patch.object(ops, "_agent_path", return_value="/usr/bin/agent"), \
                patch.object(ops.subprocess, "run", side_effect=subprocess.TimeoutExpired("agent", 1800)):
            with self.assertRaisesRegex(ops.AgentOpsError, "agent_result_unconfirmed"):
                ops._run(["issue", "owner/repo#1", "--at", "2026-10-13T15:00:00Z"])


if __name__ == "__main__":
    unittest.main()
