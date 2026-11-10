"""Node-owned deployment preview and fail-closed execution contracts."""
import unittest
from gway_remote.watchtower_exec_auth import AuthorizedExecution
from gway_remote.mcp_bearer_gateway import ALLOWED_TOOLS, EXEC_TOOL_NAMES, EXEC_TOOLS, NODE_TOOLS


class Pinned:
    class Node:
        node = "gway-001"
        host_key_sha256 = "c" * 64
    node = Node()

    def invoke(self, payload):
        return {"node": payload["node"], "request_id": payload["request_id"],
                "result": {"application": payload["application"], "status": "declared", "revision": "a"*40}}


class BrokerTests(unittest.TestCase):
    def setUp(self):
        class Service(AuthorizedExecution):
            def _allow_preview_eligibility(self, node):
                if node != "gway-001":
                    raise PermissionError("node denied")
        self.service = Service(None, None, type("Relay", (), {"transport": Pinned()})())

    def test_remote_preview(self):
        from unittest.mock import patch
        with patch("gway_remote.watchtower_exec_auth.pinned_transport", return_value=Pinned()):
            result = self.service.deployment_preview(node="gway-001", application="agentops")
            self.assertEqual(result["status"], "eligible")
            with self.assertRaises(PermissionError):
                self.service.deployment(principal="a"*24, request_id="b"*32,
                                        node="gway-001", application="agentops")

    def test_status_requires_existing_request_binding(self):
        from unittest.mock import patch
        with patch("gway_remote.watchtower_exec_auth.pinned_transport", return_value=Pinned()):
            with patch.object(self.service, "_allow", return_value=None):
                with patch.object(self.service, "_current_eligibility", return_value=None):
                    with patch.object(self.service, "ledger") as ledger:
                        ledger.get.side_effect = ValueError("request not found")
                        with self.assertRaises(ValueError):
                            self.service.deployment(principal="a"*24, request_id="b"*32,
                                node="gway-001", application="agentops", status=True)
                    with patch.object(self.service, "ledger") as ledger:
                        ledger.get.side_effect = ValueError("request not found")
                        result = self.service.deployment(principal="a"*24, request_id="b"*32,
                            node="gway-001", application="agentops")
                        self.assertEqual(result["status"], "uncertain")

    def test_ssh_nonzero_exit_is_uncertain_and_not_redispatched(self):
        import subprocess
        from unittest.mock import patch, Mock
        with patch("gway_remote.watchtower_exec_auth.pinned_transport", return_value=Pinned()):
            with patch.object(self.service, "_allow", return_value=None):
                with patch.object(self.service, "_current_eligibility", return_value=None):
                    with patch.object(self.service, "deployment_preview", return_value={"status": "eligible", "revision": "a"*40}):
                        with patch.object(self.service, "ledger") as ledger:
                            ledger.get.side_effect = [
                                ValueError("request not found"),
                                {"state": "uncertain", "node": "gway-001",
                                 "principal": "a"*24, "host_key_sha256": "c"*64,
                                 "command": 'deployment:["agentops","aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]',
                                 "command_sha256": __import__("gway_remote.watchtower_exec_transport",
                                                              fromlist=["_digest"])._digest(
                                     "gway-001", 'deployment:["agentops","aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]',
                                     "a"*24, "c"*64)}
                            ]
                            ledger.claim_dispatch.return_value = True
                            pinned = Pinned()
                            pinned.invoke = Mock(side_effect=subprocess.CalledProcessError(1, ["ssh"]))
                            with patch("gway_remote.watchtower_exec_auth.pinned_transport",
                                       return_value=pinned):
                                result = self.service.deployment(
                                    principal="a"*24, request_id="b"*32,
                                    node="gway-001", application="agentops")
                                self.assertEqual(result["status"], "uncertain")
                                ledger.mark_dispatched.assert_called_once_with(
                                    "b"*32, confirmed=False)
                                result = self.service.deployment(
                                    principal="a"*24, request_id="b"*32,
                                    node="gway-001", application="agentops")
                                self.assertEqual(result["status"], "uncertain")
                                pinned.invoke.assert_called_once()

    def test_missing_ssh_ack_is_uncertain_and_not_redispatched(self):
        from unittest.mock import patch, Mock
        with patch.object(self.service, "_allow", return_value=None):
            with patch.object(self.service, "_current_eligibility", return_value=None):
                with patch.object(self.service, "deployment_preview",
                                  return_value={"status": "eligible", "revision": "a"*40}):
                    with patch.object(self.service, "ledger") as ledger:
                        ledger.get.side_effect = [
                            ValueError("request not found"),
                            {"state": "uncertain", "node": "gway-001",
                             "principal": "a"*24, "host_key_sha256": "c"*64,
                             "command": 'deployment:["agentops","aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]',
                             "command_sha256": __import__(
                                 "gway_remote.watchtower_exec_transport",
                                 fromlist=["_digest"])._digest(
                                     "gway-001", 'deployment:["agentops","aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]',
                                     "a"*24, "c"*64)}
                        ]
                        ledger.claim_dispatch.return_value = True
                        pinned = Pinned()
                        pinned.invoke = Mock(return_value=None)
                        with patch("gway_remote.watchtower_exec_auth.pinned_transport",
                                   return_value=pinned):
                            result = self.service.deployment(
                                principal="a"*24, request_id="b"*32,
                                node="gway-001", application="agentops")
                            self.assertEqual(result["status"], "uncertain")
                            ledger.mark_dispatched.assert_called_once_with(
                                "b"*32, confirmed=False)
                            duplicate = self.service.deployment(
                                principal="a"*24, request_id="b"*32,
                                node="gway-001", application="agentops")
                            self.assertEqual(duplicate["status"], "uncertain")
                            pinned.invoke.assert_called_once()

    def test_wrong_pinned_revision_ack_is_uncertain(self):
        from unittest.mock import patch, Mock
        with patch.object(self.service, "_allow", return_value=None):
            with patch.object(self.service, "_current_eligibility", return_value=None):
                with patch.object(self.service, "deployment_preview",
                                  return_value={"status": "eligible", "revision": "a"*40}):
                    with patch.object(self.service, "ledger") as ledger:
                        ledger.get.side_effect = ValueError("request not found")
                        ledger.claim_dispatch.return_value = True
                        pinned = Pinned()
                        pinned.invoke = Mock(return_value={
                            "node": "gway-001", "request_id": "b"*32,
                            "result": {"application": "agentops", "request_id": "b"*32,
                                       "revision": "f"*40, "state": "accepted"}})
                        with patch("gway_remote.watchtower_exec_auth.pinned_transport",
                                   return_value=pinned):
                            result = self.service.deployment(
                                principal="a"*24, request_id="b"*32,
                                node="gway-001", application="agentops")
                            self.assertEqual(result["status"], "uncertain")
                            ledger.mark_dispatched.assert_called_once_with(
                                "b"*32, confirmed=False)
                            pinned.invoke.assert_called_once()

    def test_status_rejects_wrong_revision_without_terminal_reconciliation(self):
        from unittest.mock import patch, Mock
        from gway_remote.watchtower_exec_transport import _digest
        principal, rid, node, app = "a"*24, "b"*32, "gway-001", "agentops"
        binding = 'deployment:["agentops","' + "a"*40 + '"]'
        row = {"node": node, "principal": principal,
               "host_key_sha256": "c"*64, "command": binding,
               "command_sha256": _digest(node, binding, principal, "c"*64),
               "state": "dispatched"}
        pinned = Pinned()
        pinned.invoke = Mock(return_value={
            "node": node, "request_id": rid,
            "result": {"application": app, "request_id": rid,
                       "revision": "f"*40, "state": "succeeded"}})
        with patch.object(self.service, "_allow", return_value=None):
            with patch.object(self.service, "_current_eligibility", return_value=None):
                with patch.object(self.service, "ledger") as ledger:
                    ledger.get.return_value = row
                    with patch("gway_remote.watchtower_exec_auth.pinned_transport",
                               return_value=pinned):
                        with self.assertRaises(PermissionError):
                            self.service.deployment(
                                principal=principal, request_id=rid, node=node,
                                application=app, status=True)
                    ledger.record_result_state.assert_not_called()

    def test_manifest_revision_change_rejects_duplicate_without_dispatch(self):
        from unittest.mock import patch, Mock
        from gway_remote.watchtower_exec_transport import _digest
        principal, rid, node, app = "a"*24, "b"*32, "gway-001", "agentops"
        binding = 'deployment:["agentops","' + "a"*40 + '"]'
        row = {"node": node, "principal": principal,
               "host_key_sha256": "c"*64, "command": binding,
               "command_sha256": _digest(node, binding, principal, "c"*64),
               "state": "uncertain"}
        pinned = Pinned()
        pinned.invoke = Mock()
        with patch.object(self.service, "_allow", return_value=None):
            with patch.object(self.service, "_current_eligibility", return_value=None):
                with patch.object(self.service, "deployment_preview",
                                  return_value={"status": "eligible", "revision": "f"*40}):
                    with patch.object(self.service, "ledger") as ledger:
                        ledger.get.return_value = row
                        with patch("gway_remote.watchtower_exec_auth.pinned_transport",
                                   return_value=pinned):
                            with self.assertRaises(PermissionError):
                                self.service.deployment(
                                    principal=principal, request_id=rid, node=node,
                                    application=app)
                        ledger.reserve_deployment.assert_not_called()
                        ledger.claim_dispatch.assert_not_called()
                        pinned.invoke.assert_not_called()

    def test_unattested_node_cannot_reserve_or_dispatch(self):
        from unittest.mock import patch
        with patch.object(self.service, "_allow", return_value=None):
            with patch.object(self.service, "_current_eligibility",
                              side_effect=PermissionError("identity not attested")):
                with patch.object(self.service, "ledger") as ledger:
                    with self.assertRaises(PermissionError):
                        self.service.deployment(principal="a"*24, request_id="b"*32,
                                                node="gway-001", application="agentops")
                    ledger.reserve_deployment.assert_not_called()
                    ledger.claim_dispatch.assert_not_called()

    def test_negative_targets(self):
        for app in ("../bad", "agentops;id", ""):
            with self.assertRaises(ValueError):
                self.service.deployment_preview(node="gway-001", application=app)
        with self.assertRaises(PermissionError):
            self.service.deployment_preview(node="gway-002", application="agentops")

    def test_scopes_preserved(self):
        self.assertTrue({"node_deploy", "node_deploy_status"} <= EXEC_TOOL_NAMES)
        self.assertTrue({"node_deploy", "node_deploy_status"} <= ALLOWED_TOOLS)
        self.assertIn("node_deploy_preview", {t["name"] for t in NODE_TOOLS})
        for tool in EXEC_TOOLS:
            if tool["name"].startswith("node_deploy"):
                self.assertEqual(tool["_meta"]["securitySchemes"][0]["scopes"], ["gway:execute"])


if __name__ == "__main__":
    unittest.main()
