"""Agent Ops explicit issue submission boundaries."""
import subprocess
import unittest
from unittest.mock import Mock, patch

from gway_remote import agent_ops_adapter
from gway_remote.mobile import commands, execute


class AgentIssueSendTests(unittest.TestCase):
    def test_mutation_is_allowlisted_but_not_read_only(self):
        spec = next(row for row in commands() if row["name"] == "agent-issue")
        self.assertFalse(spec["read_only"])
        self.assertEqual(set(spec["arguments"]), {"ref", "at"})

    def test_invalid_ref_and_timestamp_never_launch(self):
        valid = {"ref": "arthexis/gway-agent-ops#16", "at": "2026-10-13T15:00:00Z"}
        invalid = [
            {}, {"ref": "owner/repo#1"}, dict(valid, extra="x"),
            dict(valid, ref="owner/repo#0"),
            dict(valid, ref="owner/repo#1;rm -rf /"),
            dict(valid, ref="owner/repo#1 --resend"),
            dict(valid, ref="owner/repo/pull/1"),
            dict(valid, at="2026-10-13T15:00:00+00:00"),
            dict(valid, at="2026-02-30T15:00:00Z"),
            dict(valid, at="tomorrow"),
            dict(valid, at=True),
        ]
        with patch.object(agent_ops_adapter, "_run") as runner:
            for args in invalid:
                with self.subTest(args=args), self.assertRaises(ValueError):
                    execute("agent-issue", args)
            runner.assert_not_called()

    @patch.object(agent_ops_adapter, "_agent_path", return_value="/usr/bin/agent")
    @patch.object(agent_ops_adapter.subprocess, "run")
    def test_fixed_argv_and_same_timestamp_on_retry(self, run, _path):
        run.return_value = Mock(returncode=0, stdout='{"schema_version":1,"command":"submit","status":"ok","data":{"issue":"arthexis/gway-agent-ops#16"},"error":null}')
        args = {"ref": "arthexis/gway-agent-ops#16", "at": "2026-10-13T15:00:00Z"}
        for _ in range(2):
            self.assertEqual(execute("agent-issue", args)["status"], "ok")
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertEqual(call.args[0], [
                "/usr/bin/agent", "submit", args["ref"], "--at", args["at"], "--json"])
            self.assertFalse(call.kwargs.get("shell", False))

    @patch.object(agent_ops_adapter, "_agent_path", return_value="/usr/bin/agent")
    @patch.object(agent_ops_adapter.subprocess, "run")
    def test_cli_failure_and_timeout_do_not_report_sent(self, run, _path):
        args = {"ref": "arthexis/gway-agent-ops#16", "at": "2026-10-13T15:00:00Z"}
        run.return_value = Mock(returncode=1, stdout="", stderr="locked")
        with self.assertRaisesRegex(RuntimeError, "agent_invalid_json"):
            execute("agent-issue", args)
        run.side_effect = subprocess.TimeoutExpired("agent", 20)
        with self.assertRaisesRegex(RuntimeError, "agent_result_unconfirmed"):
            execute("agent-issue", args)


if __name__ == "__main__":
    unittest.main()
