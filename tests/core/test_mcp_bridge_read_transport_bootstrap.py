"""Bridge bootstrap reuses existing authenticated node relay, without new SSH identity."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from gway_remote.mcp_bridge_bootstrap import start_bridge
from gway_remote.mcp_bridge_server import serve_gateway_session
from gway_remote.mcp_bridge_session import SessionBridgeDispatch


class SharedTransportBootstrapTests(unittest.TestCase):
    def test_bootstrap_reuses_execution_relay_without_another_transport(self):
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
            with patch.dict(os.environ, env, clear=True):
                with patch("gway_remote.mcp_bridge_bootstrap.BridgeSessions") as sessions:
                    with patch("gway_remote.mcp_bridge_bootstrap.serve_managed_sessions"):
                        with patch("gway_remote.mcp_bridge_bootstrap.threading.Thread") as thread:
                            started = start_bridge(Mock(), execution=execution)
                            self.assertEqual(len(started), 4)
                            self.assertIs(sessions.call_args.kwargs["execution"], execution)
                            self.assertNotIn("read_transport", sessions.call_args.kwargs)
                            thread.return_value.start.assert_called_once()

    def test_single_session_uses_existing_execution_relay(self):
        execution = Mock()
        verifier = Mock()
        verifier.verify.return_value = True
        with patch("gway_remote.mcp_bridge_server.BridgeUnixServer") as server:
            bridge_server = serve_gateway_session(
                "/unused/bridge.sock", key=b"k" * 32, audience="gway-001",
                verifier=verifier, session_token="trusted",
                allowed_node=lambda token, node: node == "gway-001",
                read_principal=lambda token: "reader",
                execution=execution,
            )
            self.assertIs(bridge_server, server.return_value)
            dispatch = server.call_args.args[1].dispatch
            self.assertIsInstance(dispatch, SessionBridgeDispatch)
            self.assertIs(dispatch.execution.relay.transport,
                          execution.relay.transport)


if __name__ == "__main__":
    unittest.main()
