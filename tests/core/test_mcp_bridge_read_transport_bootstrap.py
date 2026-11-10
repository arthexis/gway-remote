"""Isolated read-transport wiring regression; never reuse execute SSH credentials."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from gway_remote.mcp_bridge_bootstrap import start_bridge
from gway_remote.mcp_bridge_server import serve_gateway_session


class ReadTransportBootstrapTests(unittest.TestCase):
    def test_bootstrap_is_opt_in_and_never_implicitly_uses_execution_transport(self):
        with tempfile.TemporaryDirectory() as root:
            key = Path(root) / "bridge.key"
            key.write_bytes(b"k" * 32)
            key.chmod(0o600)
            env = {
                "GWAY_MCP_BRIDGE_ENABLED": "1",
                "GWAY_MCP_BRIDGE_KEY_FILE": str(key),
                "GWAY_MCP_BRIDGE_SOCKET": str(Path(root) / "bridge.sock"),
            }
            execution = Mock()
            distinct_read = Mock()
            with patch.dict(os.environ, env, clear=True):
                with patch("gway_remote.mcp_bridge_bootstrap.BridgeSessions") as sessions:
                    with patch("gway_remote.mcp_bridge_bootstrap.serve_managed_sessions") as server:
                        with patch("gway_remote.mcp_bridge_bootstrap.threading.Thread") as thread:
                            started = start_bridge(Mock(), execution=execution,
                                                   read_transport=distinct_read)
                            self.assertEqual(len(started), 4)
                            self.assertIs(sessions.call_args.kwargs["execution"], execution)
                            self.assertIs(sessions.call_args.kwargs["read_transport"], distinct_read)
                            thread.return_value.start.assert_called_once()
                            sessions.reset_mock()
                            start_bridge(Mock(), execution=execution)
                            self.assertIsNone(sessions.call_args.kwargs["read_transport"])
                            self.assertIs(sessions.call_args.kwargs["execution"], execution)

    def test_single_session_factory_forwards_distinct_read_transport(self):
        read_transport = Mock()
        with patch("gway_remote.mcp_bridge_server.bind_gateway_session") as binder:
            with patch("gway_remote.mcp_bridge_server.BridgeUnixServer") as server:
                serve_gateway_session(
                    "/unused/bridge.sock", key=b"k" * 32, audience="gway-002",
                    verifier=Mock(), session_token="trusted",
                    allowed_node=Mock(), read_principal=Mock(),
                    execution=Mock(), read_transport=read_transport,
                )
                self.assertIs(binder.call_args.kwargs["read_transport"], read_transport)
                server.assert_called_once()


if __name__ == "__main__":
    unittest.main()
