import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from gway_remote.android_release_candidate import Candidate,CandidateLedger
from gway_remote.android_rc_coordinator import (
    setup,reserve,bind,tracked,workflow_step,advance,historical,artifact_step,pick_run,
    CI,COMPOSE,INSTALL,ACCEPT,
)

class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/"ledger.sqlite"
        self.c=Candidate("a"*40,"b"*40,800,"0.2.800")
        self.l=CandidateLedger(self.path);self.l.allocate(self.c,published_version=799,installed_version=799)
        setup(self.l);self.g=Mock();self.g.OWNER="arthexis";self.g.REPO="arthexis/gway-remote"
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
        self.l.close();self.l=CandidateLedger(self.path);setup(self.l)
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
