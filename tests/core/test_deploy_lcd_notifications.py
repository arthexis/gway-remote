"""Unittest-compatible node/subject deployment notification acceptance."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from gway_remote.deployment_lcd_notifications import document, send
from gway_remote.deployment_sound import DeploymentSound
from gway_remote.manual_deploy_async import AsyncDeployBroker


class Ledger:
    def transition(self, request_id, expected, state):
        self.state = state
        return True


class DeployNotificationTests(unittest.TestCase):
    def test_destination_is_not_dispatch_origin(self):
        value = document("arthexis/ocpp-reports", "ocpp-abb-1",
                         "deploy-failed", "7ac2f1abcd", origin_node="gway-001")
        self.assertEqual(value["origin_node"], "gway-001")
        self.assertEqual(value["target_node"], "ocpp-abb-1")
        self.assertEqual(value["subject"], {"type": "repository",
                                           "repository": "arthexis/ocpp-reports"})
        self.assertEqual(value["state"], "deploy-failed")
        self.assertEqual(value["reason_code"], "DEPLOY_FAILED")

    def test_activation_is_not_health_verification(self):
        activated = document("arthexis/ocpp-reports", "ocpp-abb-1",
                             "deploy-activated", "abcdeffedcba", origin_node="gway-001")
        self.assertEqual(activated["reason_code"], "ACTIVATED")
        self.assertEqual(activated["severity"], "info")
        verified = document("arthexis/ocpp-reports", "ocpp-abb-1",
                            "deploy-verified", "abcdeffedcba", origin_node="gway-001")
        self.assertEqual(verified["reason_code"], "HEALTH_VERIFIED")

    def test_no_unnamed_destination_or_repository(self):
        for repository, target in (("ocpp-reports", "ocpp-abb-1"),
                                   ("arthexis/ocpp-reports", "unknown")):
            with self.subTest(repository=repository, target=target):
                with self.assertRaises(ValueError):
                    document(repository, target, "deploy-failed",
                             "abcdeffedcba", origin_node="gway-001")

    def test_non_shell_single_send_no_fallback(self):
        calls = []
        def run(args, **kw):
            calls.append(args)
            return SimpleNamespace(returncode=7)
        doc = document("arthexis/gway-remote", "gway-001", "rollback-failed",
                       "abcdef123456", origin_node="gway-001")
        self.assertFalse(send(doc, runner=run, home=Path("/tmp/homedir")))
        self.assertEqual(calls[0][:2],
                         ["/tmp/homedir/.local/bin/lcd", "notice"])
        self.assertEqual(len(calls), 1)

    def test_existing_notifier_adds_actual_node(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {
                "GWAY_DEPLOY_LCD_NOTIFICATIONS": "1"}), patch(
                "gway_remote.deployment_sound.Path.home", return_value=Path(temp)):
            runner = Mock(return_value=SimpleNamespace(returncode=0))
            notifier = DeploymentSound(
                "ocpp-reports", deployment_id="abcdeffedcba",
                database=Path(temp) / "receipts.db", run=runner,
                repository="arthexis/ocpp-reports", node="ocpp-abb-1",
                origin_node="gway-001")
            notifier("deploy-failed")
            lcd = runner.call_args_list[0].args[0]
            self.assertEqual(lcd[:2], [str(Path(temp) / ".local/bin/lcd"), "notice"])
            self.assertEqual(json.loads(lcd[2])["target_node"], "ocpp-abb-1")

    def test_broker_never_relabels_unknown_or_activation_as_verified(self):
        for state, event in (("succeeded", "deploy-activated"),
                             ("failed", "deploy-failed"),
                             ("already_current", "deploy-skipped"),
                             ("unknown", None)):
            with self.subTest(state=state), patch.dict(os.environ, {
                    "GWAY_DEPLOY_LCD_NOTIFICATIONS": "1"}):
                ledger = Ledger()
                broker = AsyncDeployBroker(
                    ledger, inventory=lambda: [], executor=lambda *_: {"state": state})
                captured = []
                class FakeSound:
                    def __init__(self, *a, **kw):
                        assert kw["node"] == "ocpp-abb-1"
                        assert kw["repository"] == "arthexis/ocpp-reports"
                    def __call__(self, msg):
                        captured.append(msg)
                with patch("gway_remote.deployment_sound.DeploymentSound", FakeSound):
                    broker._execute("ab"*16, "arthexis/ocpp-reports",
                                    "ocpp-abb-1", "a"*40)
                self.assertEqual(captured, ["deploy-started"] + ([event] if event else []))


if __name__ == "__main__":
    unittest.main()
