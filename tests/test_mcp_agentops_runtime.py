"""AgentOps runtime policy is explicit, bounded and never inherited."""
import os
import pwd
import unittest
from unittest.mock import patch, MagicMock
from gway_remote.mcp_source_registry import SourceRegistration
from gway_remote.mcp_source_stdio import _provider_environment, SourceProtocolError


class AgentOpsRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.registration = SourceRegistration(
            source_id="agentops", revision="a" * 40,
            executable="/usr/bin/python3", argv=("/usr/bin/python3", "-m", "gway_agent_ops.mcp_stdio"),
            run_as=pwd.getpwuid(os.geteuid()).pw_name, enabled=True)

    def test_no_gateway_environment_leak(self):
        with patch.dict(os.environ, {"GWAY_AGENT_WORKSPACE_ROOT": "/tmp/untrusted",
                                      "XDG_RUNTIME_DIR": "/tmp/untrusted",
                                      "GH_TOKEN": "secret"}):
            with patch("gway_remote.mcp_source_stdio.Path") as path:
                path.return_value.exists.return_value = False
                path.return_value.is_symlink.return_value = False
                env = _provider_environment(self.registration)
        for key in ("GWAY_AGENT_WORKSPACE_ROOT", "XDG_RUNTIME_DIR", "GH_TOKEN"):
            self.assertNotIn(key, env)

    def test_rejects_untrusted_runtime_file(self):
        with patch("gway_remote.mcp_source_stdio.Path") as path:
            runtime = path.return_value
            runtime.exists.return_value = True
            runtime.is_symlink.return_value = False
            runtime.is_file.return_value = True
            runtime.lstat.return_value.st_uid = 0
            runtime.lstat.return_value.st_mode = 0o100666
            runtime.lstat.return_value.st_size = 120
            with self.assertRaisesRegex(SourceProtocolError, "untrusted_provider_runtime"):
                _provider_environment(self.registration)

    def test_rejects_relative_paths(self):
        with patch("gway_remote.mcp_source_stdio.Path") as path:
            runtime = path.return_value
            runtime.exists.return_value = True
            runtime.is_symlink.return_value = False
            runtime.is_file.return_value = True
            runtime.lstat.return_value.st_uid = 0
            runtime.lstat.return_value.st_mode = 0o100644
            runtime.lstat.return_value.st_size = 120
            runtime.read_text.return_value = '{"workspace":"relative","agent_executable":"/usr/bin/agent"}'
            with self.assertRaisesRegex(SourceProtocolError, "invalid_provider_runtime"):
                _provider_environment(self.registration)


if __name__ == "__main__":
    unittest.main()
