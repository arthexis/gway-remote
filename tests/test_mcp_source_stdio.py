import os
import pwd
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch
from pathlib import Path

from gway_remote.mcp_source_registry import SourceRegistration
from gway_remote.mcp_source_stdio import (
    SourceProtocolError, list_source_tools, call_source_tool,
)

SERVER = r"""
import json
import sys
import time

tool = {"name": "ping", "description": "Read ping",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True}}
for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "notifications/initialized":
        continue
    if method == "initialize":
        result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "synthetic", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [tool]}
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": "pong"}], "isError": False}
    else:
        raise SystemExit(1)
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
"""


@unittest.skipIf(os.geteuid() == 0, "stdio client intentionally refuses root")
class StdioSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / "server.py"
        path.write_text(textwrap.dedent(SERVER))
        self.registration = SourceRegistration(
            source_id="synthetic", revision="a" * 40,
            executable=sys.executable, argv=(sys.executable, str(path)),
            run_as=pwd.getpwuid(os.geteuid()).pw_name, enabled=True)

    def test_handshake_discovery_and_call(self):
        tools = list_source_tools(self.registration)
        self.assertEqual([t["name"] for t in tools], ["ping"])
        result = call_source_tool(self.registration, "ping", {}, tools)
        self.assertEqual(result["content"][0]["text"], "pong")

    def test_denies_unapproved_call(self):
        with self.assertRaises(SourceProtocolError):
            call_source_tool(self.registration, "ping", {}, [])
        with self.assertRaises(SourceProtocolError):
            call_source_tool(self.registration, "other", {}, list_source_tools(self.registration))

    def test_provider_environment_is_bounded(self):
        from gway_remote.mcp_source_stdio import _provider_environment
        with patch.dict(os.environ, {"GH_TOKEN": "secret", "GWAY_AGENT_ALLOWED_REPOS": "untrusted"}):
            env = _provider_environment(self.registration)
        self.assertEqual(env["HOME"], pwd.getpwuid(os.geteuid()).pw_dir)
        self.assertNotIn("GH_TOKEN", env)
        self.assertNotIn("GWAY_AGENT_ALLOWED_REPOS", env)

    def test_agentops_policy_is_root_managed_and_fail_closed(self):
        from dataclasses import replace
        from gway_remote.mcp_source_stdio import _provider_environment
        agentops = replace(self.registration, source_id="agentops")
        with patch("gway_remote.mcp_source_stdio.Path") as path:
            policy = path.return_value
            policy.exists.return_value = True
            policy.is_file.return_value = True
            policy.is_symlink.return_value = False
            policy.lstat.return_value.st_uid = 0
            policy.lstat.return_value.st_mode = 0o100644
            policy.lstat.return_value.st_size = 60
            policy.read_text.return_value = "arthexis/gway-agent-ops,arthexis/gway-remote"
            env = _provider_environment(agentops)
            self.assertEqual(env["GWAY_AGENT_ALLOWED_REPOS"],
                             "arthexis/gway-agent-ops,arthexis/gway-remote")
            policy.read_text.return_value = "../bad"
            with self.assertRaises(SourceProtocolError):
                _provider_environment(agentops)
            policy.read_text.return_value = "arthexis/gway-agent-ops"
            policy.lstat.return_value.st_mode = 0o100666
            with self.assertRaises(SourceProtocolError):
                _provider_environment(agentops)

    def test_rejects_disabled_source(self):
        from dataclasses import replace
        with self.assertRaises(SourceProtocolError):
            list_source_tools(replace(self.registration, enabled=False))


if __name__ == "__main__":
    unittest.main()
