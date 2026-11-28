import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from gway_remote.android_release_candidate import Candidate,CandidateLedger
from gway_remote.android_rc_coordinator import (
    setup as setup_ledger,reserve,bind,tracked,workflow_step,advance,historical,artifact_step,pick_run,
    CI,COMPOSE,INSTALL,ACCEPT,wait_current,acceptance_attempt,
)

class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/"ledger.sqlite"
        self.c=Candidate("a"*40,"b"*40,800,"0.2.800")
        self.l=CandidateLedger(self.path);self.l.allocate(self.c,published_version=799,installed_version=799)
        setup_ledger(self.l);self.g=Mock();self.g.OWNER="arthexis";self.g.REPO="arthexis/gway-remote"
        self.g.api.side_effect=self.api
        self.rows=[];self.runs={}
    def tearDown(self):
        self.l.close();self.tmp.cleanup()
    def api(self,path):
        if path=="branches/main":return {"commit":{"sha":self.c.source_sha}}
        if path.startswith("actions/workflows/"):return {"total_count":len(self.rows),"workflow_runs":self.rows}
        if path.endswith("/jobs?per_page=100"):return {"total_count":1,"jobs":[{"name":"CI","conclusion":"success"}]}
        if path.startswith("actions/runs/"):return self.runs[int(path.split("/")[2])]
        if path.startswith("git/commits/"):return {"tree":{"sha":self.c.source_tree}}
        raise AssertionError(path)
    def run_data(self,run_id=11,status="in_progress",conclusion=None):
        return {"id":run_id,"status":status,"conclusion":conclusion,"run_attempt":1,
                "head_sha":self.c.source_sha,"actor":{"login":"arthexis"},"triggering_actor":{"login":"arthexis"}}
    def step(self,adopt=None):
        return workflow_step(self.l,self.c,self.g,"ci",CI,self.c.source_sha,{},adopt=adopt)
    def test_resume_exact_dispatch_and_terminal(self):
        self.g.create_run.return_value=11;self.runs[11]=self.run_data()
        self.assertEqual(self.step()[1]["status"],"waiting")
        self.l.close();self.l=CandidateLedger(self.path);setup_ledger(self.l)
        self.assertEqual(self.step()[0],11)
        self.runs[11]=self.run_data(status="completed",conclusion="success")
        self.assertEqual(self.step(),(11,None));self.g.create_run.assert_called_once_with(CI)
    def test_unknown_dispatch_never_replayed(self):
        self.g.create_run.side_effect=RuntimeError("lost response")
        with self.assertRaisesRegex(RuntimeError,"lost response"):self.step()
        self.assertIsNone(tracked(self.l,self.c,"ci")[1])
        with self.assertRaisesRegex(ValueError,"dispatch_uncertain"):self.step()
        self.g.create_run.assert_called_once()
    def test_reuse_existing_and_no_retry_failed(self):
        self.runs[11]=self.run_data(status="completed",conclusion="failure");self.rows=[self.runs[11]]
        for _ in range(2):
            with self.assertRaisesRegex(ValueError,"failed_review"):self.step()
        self.g.create_run.assert_not_called()
    def test_existing_acceptance_requires_explicit_adoption(self):
        self.runs[11]=self.run_data();self.rows=[self.runs[11]]
        with self.assertRaisesRegex(ValueError,"explicit_adoption"):
            pick_run(self.g,ACCEPT,self.c.source_sha)
        self.assertEqual(pick_run(self.g,ACCEPT,self.c.source_sha,adopt=11),11)
        self.g.create_run.assert_not_called()
    def test_conflict_and_retried_run(self):
        self.runs[11]=self.run_data();self.runs[11]["run_attempt"]=2
        with self.assertRaisesRegex(ValueError,"attempt_unverified"):self.step(adopt=11)
        self.assertIsNone(tracked(self.l,self.c,"ci"))
    def test_historical_is_first_and_no_dispatch(self):
        with patch("gway_remote.android_rc_coordinator.historical",return_value={"status":"published_verified"}) as verify:
            self.assertEqual(advance(self.l,self.c,self.g,Path(self.tmp.name),revision="f"*40)["status"],"published_verified")
        verify.assert_called_once();self.g.create_run.assert_not_called();self.g.api.assert_not_called()
    def test_moved_main_rejects_before_dispatch(self):
        with self.assertRaisesRegex(ValueError,"candidate_superseded"):
            advance(self.l,self.c,self.g,Path(self.tmp.name),revision="f"*40)
        self.g.create_run.assert_not_called()
    def test_signed_evidence_is_not_replayed(self):
        self.l.record(self.c.candidate_id,"built",{"run_id":10})
        self.l.record(self.c.candidate_id,"signed",{"run_id":11})
        self.assertIsNone(artifact_step(self.l,self.c,self.g,"built",self.c.source_sha,Path(self.tmp.name)))
        self.assertIsNone(artifact_step(self.l,self.c,self.g,"signed",self.c.source_sha,Path(self.tmp.name)))
        self.g.create_run.assert_not_called();self.g.api.assert_not_called()
    def test_historical_run_missing_does_not_dispatch_at_current_main(self):
        with self.assertRaisesRegex(ValueError,"historical_evidence_missing"):
            workflow_step(self.l,self.c,self.g,"old-ci",CI,"f"*40,{})
        self.g.create_run.assert_not_called()

    def test_successful_active_path_records_exact_receipt_without_publication(self):
        from gway_remote.android_release_candidate import SignedArtifact
        a=SignedArtifact(self.c,"c"*64,"d"*64,12,13)
        self.l.record(self.c.candidate_id,"built",{"run_id":10})
        self.l.record(self.c.candidate_id,"signed",{"run_id":13})
        self.l.record(self.c.candidate_id,"installed",{"install_run_id":14})
        self.l.db.execute("INSERT INTO dispatch_intent VALUES (?,?,?,?)",(self.c.candidate_id,"installed",self.l.encode({"workflow_sha":self.c.source_sha}),14))
        receipt={"run_id":15,"hosted_evidence":{"ci_run":11,"compose_run":12}}
        with patch("gway_remote.android_rc_coordinator.local_artifact",return_value=a), \
             patch("gway_remote.android_rc_coordinator.identity",return_value=a), \
             patch("gway_remote.android_rc_coordinator.reconcile") as rec, \
             patch("gway_remote.android_rc_coordinator.successful_run"), \
             patch("gway_remote.android_rc_coordinator.workflow_step",side_effect=[(11,None),(12,None),(15,None)]) as step, \
             patch("gway_remote.android_rc_coordinator.read_full_receipt",return_value=receipt):
            result=advance(self.l,self.c,self.g,Path(self.tmp.name),revision=self.c.source_sha)
            self.assertEqual(result["status"],"accepted")
            self.assertFalse(result["publication_admission"])
            self.assertEqual(self.l.read(self.c.candidate_id)["accepted"],receipt)
            self.assertEqual([call.args[3] for call in step.call_args_list],["ci","compose","acceptance"])
            rec.assert_called_once()
        self.g.create_run.assert_not_called()
        self.assertNotIn("published",self.l.read(self.c.candidate_id))

    def test_signing_requires_exact_existing_authorization(self):
        self.l.record(self.c.candidate_id,"built",{"run_id":10,"artifact_id":12,"unsigned_sha256":"f"*64})
        with patch("gway_remote.android_rc_coordinator.pin",return_value="false"):
            r=artifact_step(self.l,self.c,self.g,"signed",self.c.source_sha,Path(self.tmp.name))
        self.assertEqual(r["status"],"operator_signing_authorization_required")
        self.assertEqual(r["required_pins"]["RC_APPROVED_UNSIGNED_SHA256"],"f"*64)
        self.g.create_run.assert_not_called();self.g.gh.assert_not_called()

    def test_approval_wait_and_restore_only_matching_signing_switch(self):
        from gway_remote.android_rc_coordinator import signing_pins
        built={"run_id":10,"artifact_id":12,"unsigned_sha256":"f"*64}
        self.l.record(self.c.candidate_id,"built",built)
        self.l.db.execute("INSERT INTO dispatch_intent VALUES (?,?,?,?)",(self.c.candidate_id,"signed",self.l.encode({"workflow_sha":self.c.source_sha}),13))
        self.runs[13]=self.run_data(13,status="waiting")
        self.assertEqual(artifact_step(self.l,self.c,self.g,"signed",self.c.source_sha,Path(self.tmp.name))["status"],"operator_signing_approval_required")
        self.g.gh.assert_not_called()
        self.runs[13]=self.run_data(13,status="completed",conclusion="success")
        pins=signing_pins(self.c,built,self.c.source_sha)
        pins["ANDROID_RC_SIGNING_ENABLED"]="true"
        pins["RC_PRODUCTION_CERT_SHA256"]="d"*64
        self.g.gh.side_effect=lambda *a,**k:pins.update(ANDROID_RC_SIGNING_ENABLED="false")
        with patch("gway_remote.android_rc_coordinator.pin",side_effect=lambda _,name:pins[name]), \
             patch("gway_remote.android_rc_coordinator.successful_run"), \
             patch("gway_remote.android_rc_coordinator.reconcile_artifact") as rec:
            self.assertIsNone(artifact_step(self.l,self.c,self.g,"signed",self.c.source_sha,Path(self.tmp.name)))
            rec.assert_called_once()
        self.assertEqual(pins["ANDROID_RC_SIGNING_ENABLED"],"false")
        self.g.create_run.assert_not_called()

    def test_lost_response_can_be_explicitly_reconciled_without_dispatch(self):
        self.g.create_run.side_effect=RuntimeError("lost response")
        with self.assertRaises(RuntimeError):self.step()
        self.runs[11]=self.run_data(status="completed",conclusion="success")
        self.assertEqual(self.step(adopt=11),(11,None))
        self.assertEqual(tracked(self.l,self.c,"ci")[1],11)
        self.g.create_run.assert_called_once()

    def test_wait_polls_only_current_run(self):
        self.runs[11]=self.run_data(status="completed",conclusion="success")
        self.assertTrue(wait_current(self.g,{"run_id":11,"stage":"ci"},100,
                                     clock=lambda:0,pause=lambda _:None))
        self.g.api.assert_called_once_with("actions/runs/11")
        self.g.create_run.assert_not_called()

    def test_explicit_failed_acceptance_retry_is_append_only(self):
        spec={"workflow":ACCEPT,"revision":self.c.source_sha,"inputs":{"scope":"full"}}
        reserve(self.l,self.c,"acceptance",spec,21)
        failed=self.run_data(21,status="completed",conclusion="failure")
        self.runs[21]=failed;self.rows=[failed]
        orig=self.g.api.side_effect
        self.g.api.side_effect=lambda path: {"total_count":0,"artifacts":[]} if path.endswith("/artifacts?per_page=100") else orig(path)
        self.assertEqual(acceptance_attempt(self.l,self.c,self.g,None),("acceptance",()))
        stage,excluded=acceptance_attempt(self.l,self.c,self.g,21)
        self.assertEqual((stage,excluded),("acceptance-retry:21",(21,)))
        self.g.create_run.return_value=22;self.runs[22]=self.run_data(22)
        self.assertEqual(workflow_step(self.l,self.c,self.g,stage,ACCEPT,self.c.source_sha,{"scope":"full"},exclude=excluded)[0],22)
        self.assertEqual(acceptance_attempt(self.l,self.c,self.g,21),(stage,excluded))
        self.assertEqual(acceptance_attempt(self.l,self.c,self.g,None),(stage,excluded))
        self.assertEqual(tracked(self.l,self.c,"acceptance")[1],21)
        self.g.create_run.assert_called_once_with(ACCEPT,scope="full")

    def test_retry_rejects_success_or_existing_receipt(self):
        spec={"workflow":ACCEPT,"revision":self.c.source_sha,"inputs":{"scope":"full"}}
        reserve(self.l,self.c,"acceptance",spec,21)
        self.runs[21]=self.run_data(21,status="completed",conclusion="success")
        with self.assertRaisesRegex(ValueError,"terminal_failure"):
            acceptance_attempt(self.l,self.c,self.g,21)
        self.runs[21]["conclusion"]="failure"
        orig=self.g.api.side_effect
        self.g.api.side_effect=lambda path: {"total_count":1,"artifacts":[{"name":"android-rc-full-21"}]} if path.endswith("/artifacts?per_page=100") else orig(path)
        with self.assertRaisesRegex(ValueError,"receipt_exists"):
            acceptance_attempt(self.l,self.c,self.g,21)
        self.g.create_run.assert_not_called()
