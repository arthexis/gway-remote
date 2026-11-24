"""Deploy notifications distinguish executor from target and preserve receipts."""
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from gway_remote.deployment_lcd_notifications import document, send
from gway_remote.deployment_sound import DeploymentSound
from gway_remote.manual_deploy_async import AsyncDeployBroker


def test_explicit_destination_not_dispatch_origin():
    value = document("arthexis/ocpp-reports","ocpp-abb-1","deploy-failed",
                     "7ac2f1abcd",origin_node="gway-001")
    assert value["origin_node"] == "gway-001"
    assert value["target_node"] == "ocpp-abb-1"
    assert value["subject"] == {"type": "repository",
                                "repository": "arthexis/ocpp-reports"}
    assert value["state"] == "deploy-failed"
    assert value["reason_code"] == "DEPLOY_FAILED"
    assert value["episode_id"] == "7ac2f1abcd"


def test_activate_is_not_independently_verified():
    activated = document("arthexis/ocpp-reports","ocpp-abb-1",
                         "deploy-activated","abcdeffedcba",origin_node="gway-001")
    assert activated["reason_code"] == "ACTIVATED"
    assert activated["severity"] == "info"
    verified = document("arthexis/ocpp-reports","ocpp-abb-1",
                        "deploy-verified","abcdeffedcba",origin_node="gway-001")
    assert verified["reason_code"] == "HEALTH_VERIFIED"


def test_no_unknown_node_or_repository_accepted():
    with pytest.raises(ValueError):
        document("ocpp-reports","unknown","deploy-failed","abcdeffedcba",
                 origin_node="gway-001")
    with pytest.raises(ValueError):
        document("arthexis/ocpp-reports","unknown","deploy-verified",
                 "abcdeffedcba",origin_node="gway-001")


def test_no_shell_or_fallback_on_failed_transmission():
    calls = []
    def run(args,**kw):
        calls.append(args)
        return SimpleNamespace(returncode=7)
    doc = document("arthexis/gway-remote","gway-001","rollback-failed",
                   "abcdef123456",origin_node="gway-001")
    assert not send(doc,runner=run,home=Path("/tmp/homedir"))
    assert calls[0][:2] == ["/tmp/homedir/.local/bin/lcd","notice"]
    assert len(calls)==1


def test_existing_deployment_notifier_can_publish_node_bound_lcd(monkeypatch,tmp_path):
    monkeypatch.setenv("GWAY_DEPLOY_LCD_NOTIFICATIONS","1")
    with patch("gway_remote.deployment_sound.Path.home",return_value=tmp_path):
        runner=Mock(return_value=SimpleNamespace(returncode=0))
        sound=DeploymentSound("ocpp-reports",deployment_id="abcdeffedcba",
                              database=tmp_path/"receipts.db",run=runner,
                              repository="arthexis/ocpp-reports",node="ocpp-abb-1",
                              origin_node="gway-001")
        sound("deploy-failed")
        lcd=runner.call_args_list[0].args[0]
        assert lcd[:2] == [str(tmp_path/".local/bin/lcd"),"notice"]
        import json
        assert json.loads(lcd[2])["target_node"] == "ocpp-abb-1"


class Ledger:
    def transition(self,request_id,expected,state):
        self.state=state
        return True


@pytest.mark.parametrize("state,event",[
    ("succeeded","deploy-activated"), ("failed","deploy-failed"),
    ("already_current","deploy-skipped"), ("unknown",None),
])
def test_manual_broker_emits_only_evidence_based_states(monkeypatch,state,event):
    monkeypatch.setenv("GWAY_DEPLOY_LCD_NOTIFICATIONS","1")
    ledger=Ledger()
    executor=lambda repo,node,sha: {"state":state}
    broker=AsyncDeployBroker(ledger,inventory=lambda:[],executor=executor)
    captured=[]
    class FakeSound:
        def __init__(self,*a,**kw):
            assert kw["node"]=="ocpp-abb-1"
            assert kw["repository"]=="arthexis/ocpp-reports"
        def __call__(self,event):
            captured.append(event)
    with patch("gway_remote.deployment_sound.DeploymentSound",FakeSound):
        broker._execute("ab"*16,"arthexis/ocpp-reports",
                        "ocpp-abb-1","a"*40)
    assert captured == ["deploy-started"] + ([event] if event else [])
