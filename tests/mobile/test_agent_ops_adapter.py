import unittest
from unittest.mock import patch, Mock
from gway_remote import agent_ops_adapter
from gway_remote.mobile import commands, execute


class AgentOpsAdapterTests(unittest.TestCase):
    def test_read_only_mobile_operations_are_advertised(self):
        advertised = {item["name"]: item for item in commands()}
        for name in ("agent-issues", "agent-status"):
            self.assertTrue(advertised[name]["read_only"])
            self.assertEqual(advertised[name]["arguments"], {})

    def test_invalid_arguments_never_execute(self):
        for name in ("agent-issues", "agent-status"):
            with self.subTest(name=name), patch.object(agent_ops_adapter, "_run") as runner:
                with self.assertRaisesRegex(ValueError, "invalid_arguments"):
                    execute(name, {"extra": "value"})
                runner.assert_not_called()

    @patch.object(agent_ops_adapter, "_agent_path", return_value="/usr/local/bin/agent")
    @patch.object(agent_ops_adapter.subprocess, "run")
    def test_exact_argv_no_shell(self, run, _path):
        run.return_value = Mock(returncode=0, stdout='{"schema_version":1,"command":"issues","status":"ok","data":{"issues":[]},"error":null}')
        self.assertEqual(execute("agent-issues", {})["data"], {"issues": []})
        self.assertEqual(run.call_args.args[0], ["/usr/local/bin/agent", "issues", "--json"])
        self.assertEqual(run.call_args.kwargs["timeout"], 20)
        self.assertFalse(run.call_args.kwargs["check"])
        from gway_remote.agent_issue_repositories import allowed_issue_repositories
        expected = ",".join(allowed_issue_repositories())
        self.assertIn("arthexis/gway-bastion", allowed_issue_repositories())
        self.assertEqual(run.call_args.kwargs["env"]["GWAY_AGENT_ALLOWED_REPOS"], expected)


    @patch.object(agent_ops_adapter, "_agent_path", return_value="/usr/local/bin/agent")
    @patch.object(agent_ops_adapter.subprocess, "run")
    def test_invalid_json_is_an_error(self, run, _path):
        run.return_value = Mock(returncode=0, stdout="not-json")
        with self.assertRaisesRegex(RuntimeError, "agent_invalid_json"):
            execute("agent-status", {})


if __name__ == "__main__":
    unittest.main()
