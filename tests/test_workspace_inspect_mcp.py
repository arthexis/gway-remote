"""MCP workspace inspection registration and fail-closed behavior."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.mcp_bearer_gateway import ALLOWED_TOOLS, NODE_TOOLS, READ_SECURITY
from gway_remote.mcp_bridge_gateway_dispatch import OPERATIONS
from gway_remote.mcp_workspace_inspect import inspect_authorized


class WorkspaceInspectMCPTests(unittest.TestCase):
    def test_catalog_is_read_only(self):
        self.assertIn("workspace_inspect", ALLOWED_TOOLS)
        tool = next(tool for tool in NODE_TOOLS if tool["name"] == "workspace_inspect")
        self.assertTrue(tool["annotations"]["readOnlyHint"])
        self.assertEqual(tool["_meta"], READ_SECURITY)
        self.assertEqual(OPERATIONS["workspace_inspect"], ("workspace.inspect", "gway:read"))
        self.assertFalse(tool["inputSchema"]["additionalProperties"])

    def test_rejects_unconfigured_workspace(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(PermissionError):
                inspect_authorized({"node": "gway-001", "repository": "arthexis/gway-remote"})

    def test_rejects_cross_node_and_extra_arguments(self):
        with patch.dict(os.environ, {"GWAY_WORKSPACE_NODE": "gway-001"}, clear=True):
            with self.assertRaises(PermissionError):
                inspect_authorized({"node": "gway-002", "repository": "owner/repo"})
            with self.assertRaises(ValueError):
                inspect_authorized({"node": "gway-001", "repository": "owner/repo", "path": "/tmp"})

    def test_rejects_world_writable_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "workspaces.json"
            config.write_text('{"owner/repo":"/tmp"}')
            config.chmod(0o666)
            with patch.dict(os.environ, {"GWAY_WORKSPACE_NODE": "gway-001",
                                         "GWAY_WORKSPACE_INSPECT_CONFIG": str(config)}):
                with self.assertRaises(PermissionError):
                    inspect_authorized({"node": "gway-001", "repository": "owner/repo"})


if __name__ == "__main__":
    unittest.main()
