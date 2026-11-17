"""AgentOps runtime policy is explicit, bounded and never inherited."""
import json
import os
import pwd
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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


    def _with_runtime(self, root, settings):
        """Use a synthetic root-owned policy, real user-owned CLI paths."""
        runtime = MagicMock()
        runtime.exists.return_value = True
        runtime.is_symlink.return_value = False
        runtime.is_file.return_value = True
        runtime.lstat.return_value = SimpleNamespace(
            st_uid=0, st_mode=0o100644, st_size=160)
        runtime.read_text.return_value = json.dumps(settings)
        real_path = Path

        def mapped(value):
            if value == "/etc/gway-mcp-providers/agentops.runtime.json":
                return runtime
            if value == "/etc/gway-mcp-providers/agentops.repositories":
                return real_path(root) / "no-repository-policy"
            if value == "/run/user":
                return real_path(root) / "no-user-bus"
            return real_path(value)

        with patch("gway_remote.mcp_source_stdio.Path", side_effect=mapped):
            with patch.dict(os.environ, {"GH_TOKEN": "not-inherited",
                                          "GWAY_AGENT_SEED_CODEX_HOME": "/tmp/unsafe",
                                          "PATH": "/tmp/unsafe"}):
                return _provider_environment(self.registration)

    def _fixture(self, root):
        base = Path(root)
        workspace = base / "workspace"
        workspace.mkdir(mode=0o700)
        agent = base / "release" / "bin" / "agent"
        agent.parent.mkdir(parents=True, mode=0o700)
        agent.write_text("#!/bin/sh\\nexit 0\\n")
        agent.chmod(0o700)
        binary = base / "codex-package" / "cli.js"
        binary.parent.mkdir(mode=0o700)
        binary.write_text("#!/bin/sh\\nexit 0\\n")
        binary.chmod(0o700)
        codex = base / "codex-bin" / "codex"
        codex.parent.mkdir(mode=0o700)
        codex.symlink_to(binary)
        return {"workspace": str(workspace), "agent_executable": str(agent)}, codex, binary

    def test_legacy_runtime_policy_remains_unchanged(self):
        with tempfile.TemporaryDirectory() as root:
            settings, codex, binary = self._fixture(root)
            env = self._with_runtime(root, settings)
            self.assertEqual(env["PATH"], str(Path(settings["agent_executable"]).parent) + ":/usr/bin:/bin")
            self.assertNotIn("GH_TOKEN", env)
            self.assertNotIn("GWAY_AGENT_SEED_CODEX_HOME", env)

    def test_explicit_codex_link_is_checked_and_only_its_directory_added(self):
        with tempfile.TemporaryDirectory() as root:
            settings, codex, binary = self._fixture(root)
            settings["codex_executable"] = str(codex)
            env = self._with_runtime(root, settings)
            self.assertEqual(env["PATH"], str(Path(settings["agent_executable"]).parent)
                             + ":" + str(codex.parent) + ":/usr/bin:/bin")
            self.assertEqual(env["GWAY_AGENT_WORKSPACE_ROOT"], settings["workspace"])
            self.assertNotIn("GH_TOKEN", env)
            self.assertNotIn("GWAY_AGENT_SEED_CODEX_HOME", env)

    def test_codex_world_writable_file_or_parent_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            settings, codex, binary = self._fixture(root)
            settings["codex_executable"] = str(codex)
            binary.chmod(0o777)
            with self.assertRaisesRegex(SourceProtocolError, "invalid_provider_runtime"):
                self._with_runtime(root, settings)
            binary.chmod(0o700)
            codex.parent.chmod(0o777)
            with self.assertRaisesRegex(SourceProtocolError, "invalid_provider_runtime"):
                self._with_runtime(root, settings)

    def test_unknown_runtime_fields_and_missing_codex_refused(self):
        with tempfile.TemporaryDirectory() as root:
            settings, codex, binary = self._fixture(root)
            with self.assertRaisesRegex(SourceProtocolError, "invalid_provider_runtime"):
                self._with_runtime(root, {**settings, "GH_TOKEN": "fake"})
            settings["codex_executable"] = str(codex.parent / "not-codex")
            with self.assertRaisesRegex(SourceProtocolError, "invalid_provider_runtime"):
                self._with_runtime(root, settings)



if __name__ == "__main__":
    unittest.main()
