import unittest
from unittest.mock import Mock, patch
from gway_remote import agent_ops_adapter as ops
from gway_remote.mobile import execute, commands


class AgentObservationTransportTests(unittest.TestCase):
    def test_read_only_catalog(self):
        spec = next(x for x in commands() if x["name"] == "agent-observe")
        self.assertTrue(spec["read_only"])
        self.assertEqual(set(spec["arguments"]), {"ref", "at"})

    def test_validated_fixed_argv(self):
        arguments = {"ref": "arthexis/gway-agent-ops#16", "at": "2026-10-13T15:00:00Z"}
        envelope = '{"schema_version":1,"command":"observe","status":"ok","data":{"state":"accepted"},"error":null}'
        with patch.object(ops, "_agent_path", return_value="/usr/bin/agent"), \
                patch.object(ops.subprocess, "run", return_value=Mock(
                    returncode=0, stdout=envelope)) as runner:
            self.assertEqual(execute("agent-observe", arguments)["data"]["state"], "accepted")
            self.assertEqual(runner.call_args.args[0],
                             ["/usr/bin/agent", "observe", arguments["ref"], "--at", arguments["at"], "--json"])
            self.assertEqual(runner.call_args.kwargs["timeout"], 20)

    def test_bad_identity_never_launches(self):
        with patch.object(ops, "_run") as runner:
            with self.assertRaises(ValueError):
                execute("agent-observe", {"ref": "owner/repo/pull/5", "at": "2026-10-13T15:00:00Z"})
            runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
