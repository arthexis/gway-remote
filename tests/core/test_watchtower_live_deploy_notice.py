"""Live Watchtower deployment receipt notifications: no SSH or hardware."""
from datetime import datetime, timezone
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

from gway_remote.watchtower_deploy_notices import emit, REPOSITORIES
from gway_remote.watchtower_exec_auth import AuthorizedExecution
from gway_remote.watchtower_exec_transport import _digest

RID="a"*32
PRINCIPAL="b"*24
SHA="c"*40


class Pinned:
    class Node:
        host_key_sha256="d"*64
    node=Node()
    def invoke(self, payload):
        return {"node":payload["node"],"request_id":payload["request_id"],
                "result":{"application":payload["application"],"request_id":payload["request_id"],
                          "revision":SHA,"state":"failed"}}


class LiveBrokerLCDTests(unittest.TestCase):
    def test_internal_bridge_preserves_authority_and_target(self):
        observed=[]
        def sender(event):
            observed.append(event)
            return {"status":"succeeded"}
        with patch.dict(os.environ,{"GWAY_BROKER_LCD_NOTIFICATIONS":"1"}):
            ok=emit("agentops","ocpp-abb-1",RID,"failed",dispatch=sender,
                    now=datetime(2026,11,24,7,0,tzinfo=timezone.utc))
        self.assertTrue(ok)
        self.assertEqual(len(observed),2)
        lcd,sound=observed
        self.assertEqual(lcd["origin"],"watchtower")
        self.assertEqual(lcd["node"],"gway-001")
        self.assertEqual(lcd["action"],"notice")
        doc=lcd["arguments"]["notice"]
        self.assertEqual(doc["origin_node"],"gelectriic.com")
        self.assertEqual(doc["target_node"],"ocpp-abb-1")
        self.assertEqual(doc["subject"]["repository"],"arthexis/gway-agent-ops")
        self.assertEqual(doc["state"],"deploy-failed")
        self.assertEqual(sound["device"],"sound")
        self.assertEqual(sound["arguments"],{"name":"error"})
        self.assertNotEqual(lcd["request_id"],sound["request_id"])

    def test_activation_is_silent_not_verified(self):
        observed=[]
        with patch.dict(os.environ,{"GWAY_BROKER_LCD_NOTIFICATIONS":"1"}):
            self.assertTrue(emit("ocpp_reports","ocpp-abb-1",RID,"succeeded",
                dispatch=lambda e: (observed.append(e) or {"status":"succeeded"})))
        self.assertEqual(len(observed),1)
        self.assertEqual(observed[0]["arguments"]["notice"]["state"],"deploy-activated")

    def test_off_unknown_or_unmapped_rejected_without_dispatch(self):
        seen=[]
        def send(event):
            seen.append(event)
            return {"status":"succeeded"}
        with patch.dict(os.environ,{"GWAY_BROKER_LCD_NOTIFICATIONS":"0"}):
            self.assertFalse(emit("agentops","gway-001",RID,"failed",dispatch=send))
        with patch.dict(os.environ,{"GWAY_BROKER_LCD_NOTIFICATIONS":"1"}):
            self.assertFalse(emit("unmapped","gway-001",RID,"failed",dispatch=send))
            self.assertFalse(emit("agentops","gway-001",RID,"uncertain",dispatch=send))
            self.assertFalse(emit("agentops","gway-001","bad-request-id","failed",dispatch=send))
        self.assertEqual(seen,[])

    def test_uncertain_bridge_does_not_retry_or_affect_receipt(self):
        count=[]
        def fail(event):
            count.append(event)
            raise RuntimeError("remote response uncertain")
        with patch.dict(os.environ,{"GWAY_BROKER_LCD_NOTIFICATIONS":"1"}):
            self.assertFalse(emit("agentops","gway-001",RID,"failed",dispatch=fail))
        self.assertEqual(len(count),1)

    def test_correlated_broker_status_notifies_only_on_first_terminal(self):
        from unittest.mock import patch
        node="gway-001"; app="agentops"
        binding='deployment:["agentops","' + SHA + '"]'
        row={"node":node,"principal":PRINCIPAL,"host_key_sha256":"d"*64,
             "command":binding,"command_sha256":_digest(node,binding,PRINCIPAL,"d"*64),
             "state":"dispatched"}
        class Permit(AuthorizedExecution):
            def _allow(self, p): return None
            def _current_eligibility(self,n): return None
        ledger=Mock()
        ledger.get.return_value=row
        ledger.record_result_state.return_value=None
        transport=Mock()
        svc=Permit(ledger,None,SimpleNamespace(transport=transport,enabled=True),enabled=True)
        pinned=Pinned()
        with patch("gway_remote.watchtower_exec_auth.pinned_transport",return_value=pinned):
            with patch.object(svc,"_deployment_notice") as notice:
                receipt=svc.deployment(principal=PRINCIPAL,request_id=RID,
                                       node=node,application=app,status=True)
                self.assertEqual(receipt["result"]["state"],"failed")
                notice.assert_called_once_with(app,node,RID,"failed")
        row["state"]="failed"
        with patch("gway_remote.watchtower_exec_auth.pinned_transport",return_value=pinned):
            with patch.object(svc,"_deployment_notice") as notice:
                svc.deployment(principal=PRINCIPAL,request_id=RID,
                               node=node,application=app,status=True)
                notice.assert_not_called()


if __name__=="__main__":
    unittest.main()
