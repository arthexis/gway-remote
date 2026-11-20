import os
import tempfile
import unittest
from unittest.mock import patch

from gway_remote.mcp_bridge_bootstrap import start_bridge


class BridgeBootstrapTests(unittest.TestCase):
    def test_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(start_bridge(object()))

    def test_missing_config_fails_closed(self):
        with patch.dict(os.environ, {"GWAY_MCP_BRIDGE_ENABLED": "1"}, clear=True):
            with self.assertRaises(KeyError):
                start_bridge(object())

    def test_rejects_relative_paths(self):
        with patch.dict(os.environ, {
            "GWAY_MCP_BRIDGE_ENABLED": "1",
            "GWAY_MCP_BRIDGE_KEY_FILE": "relative-key",
            "GWAY_MCP_BRIDGE_SOCKET": "/tmp/test-bridge.sock",
        }, clear=True):
            with self.assertRaises(ValueError):
                start_bridge(object())

    def test_rejects_insecure_key_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            key = os.path.join(directory, "key")
            with open(key, "wb") as stream:
                stream.write(b"x" * 32)
            os.chmod(key, 0o644)
            with patch.dict(os.environ, {
                "GWAY_MCP_BRIDGE_ENABLED": "1",
                "GWAY_MCP_BRIDGE_KEY_FILE": key,
                "GWAY_MCP_BRIDGE_SOCKET": os.path.join(directory, "bridge.sock"),
            }, clear=True):
                with self.assertRaises(PermissionError):
                    start_bridge(object())


if __name__ == "__main__":
    unittest.main()
