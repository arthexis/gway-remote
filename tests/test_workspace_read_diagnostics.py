"""Offline regression tests for read-only MCP diagnostics and receipt boundaries."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.mcp_workspace_inspect import WorkspaceUnavailable, inspect_authorized
from gway_remote.mcp_bridge_transport import BridgeReadUnavailable, AuthenticatedBridge, sign_reply


class WorkspaceReadDiagnosticsTests(unittest.TestCase):
    def test_bridge_codes_are_allowlisted(self):
        self.assertEqual(BridgeReadUnavailable("workspace_not_configured").code,
                         "workspace_not_configured")
        with self.assertRaises(ValueError):
            BridgeReadUnavailable("/private/secret/path")

    def test_unconfigured_and_wrong_node_have_safe_codes(self):
        with patch.dict("os.environ", {"GWAY_WORKSPACE_NODE": "gway-001"}, clear=True):
            with self.assertRaises(WorkspaceUnavailable) as cm:
                inspect_authorized({"node": "gway-002", "repository": "arthexis/ocpp-reports"})
            self.assertEqual(cm.exception.code, "node_binding_mismatch")
            with self.assertRaises(WorkspaceUnavailable) as cm:
                inspect_authorized({"node": "gway-001", "repository": "arthexis/ocpp-reports"})
            self.assertEqual(cm.exception.code, "workspace_not_configured")

    def test_allowlist_and_missing_receipt_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "roots.json"
            config.write_text(json.dumps({"arthexis/ocpp-reports": temp}))
            config.chmod(0o600)
            env = {"GWAY_WORKSPACE_NODE": "gway-001",
                   "GWAY_WORKSPACE_INSPECT_CONFIG": str(config)}
            with patch.dict("os.environ", env, clear=True):
                with self.assertRaises(WorkspaceUnavailable) as cm:
                    inspect_authorized({"node": "gway-001", "repository": "other/repo"})
                self.assertEqual(cm.exception.code, "repository_not_allowlisted")
                result = inspect_authorized({"node": "gway-001",
                                             "repository": "arthexis/ocpp-reports"})
                self.assertEqual(result["deployment"]["state"], "unknown")
                self.assertEqual(result["deployment"]["reason"], "deployment evidence not supplied")

    def test_unverified_receipt_cannot_claim_activation(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "roots.json"
            config.write_text(json.dumps({"arthexis/ocpp-reports": temp}))
            config.chmod(0o600)
            env = {"GWAY_WORKSPACE_NODE": "gway-001",
                   "GWAY_WORKSPACE_INSPECT_CONFIG": str(config)}
            with patch.dict("os.environ", env, clear=True):
                result = inspect_authorized(
                    {"node": "gway-001", "repository": "arthexis/ocpp-reports"},
                    deployment_receipt={"repository": "arthexis/ocpp-reports",
                                        "installation_state": "activated",
                                        "activated_revision": "a" * 40,
                                        "evidence": []})
                self.assertEqual(result["deployment"]["state"], "unknown")
                verified = inspect_authorized(
                    {"node": "gway-001", "repository": "arthexis/ocpp-reports"},
                    deployment_receipt={"repository": "arthexis/ocpp-reports",
                                        "installation_state": "activated",
                                        "activated_revision": "a" * 40,
                                        "runtime_state": "healthy",
                                        "evidence": ["verified_active_release"]})
                self.assertEqual(verified["deployment"]["installed_sha"], "a" * 40)
                self.assertEqual(verified["deployment"]["runtime_state"], "healthy")


if __name__ == "__main__":
    unittest.main()
