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

    @patch.object(agent_ops_adapter, "_agent_path", return_value="/usr/bin/agent")
    @patch.object(agent_ops_adapter.subprocess, "run")
    def test_cli_failure_preserves_safe_error_code(self, run, _path):
        run.return_value = Mock(returncode=1, stdout='{"schema_version":1,"command":"issues","status":"error","data":{},"error":{"code":"repository_registry_unavailable"}}')
        with self.assertRaisesRegex(agent_ops_adapter.AgentOpsError, "agent_repository_registry_unavailable"):
            agent_ops_adapter.issues({})

    def test_invalid_ref_and_timestamp_never_launch(self):
        valid = {"ref": "arthexis/gway-agent-ops#16", "at": "2026-10-13T15:00:00Z"}
        invalid = [
            {}, {"ref": "owner/repo#1"}, dict(valid, extra="x"),
            dict(valid, ref="owner/repo#0"),
            dict(valid, ref="owner/repo#1;rm -rf /"),
            dict(valid, ref="owner/repo#1 --resend"),
            dict(valid, ref="owner/repo/pull/1"),
            dict(valid, at="2026-10-13T15:00:00"),
            dict(valid, at="2026-10-13T15:00:00.1234567Z"),
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
                "/usr/bin/agent", "submit", args["ref"], "--at", "2026-10-13T15:00:00.000000Z", "--origin", "remote-api", "--json"])
            self.assertFalse(call.kwargs.get("shell", False))

    @patch.object(agent_ops_adapter, "_run")
    def test_timestamp_observation_canonicalizes_without_dispatch(self, run):
        values = {
            "2026-10-21T23:17:47Z": "2026-10-21T23:17:47.000000Z",
            "2026-10-21T23:17:47.000000Z": "2026-10-21T23:17:47.000000Z",
            "2026-10-21T23:17:47.123Z": "2026-10-21T23:17:47.123000Z",
            "2026-10-21T17:17:47-06:00": "2026-10-21T23:17:47.000000Z",
            "2026-10-22T00:17:47+01:00": "2026-10-21T23:17:47.000000Z",
        }
        for supplied, expected in values.items():
            with self.subTest(supplied=supplied):
                agent_ops_adapter.observe_issue({"ref": "arthexis/gway-bastion#2", "at": supplied})
                run.assert_called_with(["observe", "arthexis/gway-bastion#2", "--at", expected])
        self.assertEqual(run.call_count, len(values))
        for invalid in ("bad", "2026-02-30T00:00:00Z", "2026-10-21T23:17:47.1234567Z", "2026-10-21T23:17:47"):
            with self.assertRaises(ValueError):
                agent_ops_adapter.observe_issue({"ref": "arthexis/gway-bastion#2", "at": invalid})
        self.assertEqual(run.call_count, len(values))

    @patch.object(agent_ops_adapter, "_run")
    def test_submission_offset_and_observe_same_identity(self, run):
        ref = "arthexis/gway-bastion#2"
        submitted = {"ref": ref, "at": "2026-10-21T17:17:47-06:00"}
        agent_ops_adapter.send_issue(submitted)
        agent_ops_adapter.observe_issue({"ref": ref, "at": "2026-10-21T23:17:47.000000Z"})
        self.assertEqual(run.call_args_list[0].args[0][3], run.call_args_list[1].args[0][3])
        self.assertEqual(run.call_args_list[0].args[0][3], "2026-10-21T23:17:47.000000Z")

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
