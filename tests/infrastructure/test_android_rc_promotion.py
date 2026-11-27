import base64
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from gway_remote.android_release_candidate import Candidate, SignedArtifact
from gway_remote.android_rc_acceptance import SMOKE_CHECKS, FULL_CHECKS, smoke_receipt, full_receipt
from gway_remote.android_rc_contracts import GROUPS
from gway_remote.android_rc_promotion import (CONFIRM, HOLD_LINE, validate_revision,
    validate_full_receipt, verify_release_asset, publish_exact)


class PromotionTests(unittest.TestCase):
    def setUp(self):
        self.c = Candidate("a"*40, "b"*40, 800, "0.2.800")
        self.data = b"mock signed artifact"*1000
        self.digest = hashlib.sha256(self.data).hexdigest()
        self.a = SignedArtifact(self.c,self.digest,"d"*64,10,20)
        self.hosted = {"ci_run":31,"compose_run":32,"build_run":33,"contract_artifact_id":34,
                       "hosted_groups":dict.fromkeys(GROUPS,"pass")}
        self.full = full_receipt(self.a,30,smoke_receipt(self.a,30,dict.fromkeys(SMOKE_CHECKS,"pass")),self.hosted)
        self.old = HOLD_LINE+"\n# LEGACY_ANDROID_PUBLISHER_RETIRED\nname: Android APK\n"
        self.new = self.old.replace(HOLD_LINE+"\n","")
        self.tag = "android-v0.2.800"

    def policy_gate(self, current, source, files=None):
        gate = Mock()
        def api(path):
            if path == "branches/main":
                return {"commit":{"sha":current}}
            if path.startswith("git/commits/"):
                return {"tree":{"sha":self.c.source_tree}}
            if path.startswith("contents/"):
                value = source if path.endswith(current) else self.old
                return {"encoding":"base64","content":base64.b64encode(value.encode()).decode()}
            if path.startswith("compare/"):
                return {"status":"ahead","total_commits":1,"merge_base_commit":{"sha":self.c.source_sha},
                        "files":files or [{"filename":".github/workflows/android.yml","status":"modified"}]}
            raise AssertionError(path)
        gate.api.side_effect = api
        return gate

    def test_hold_and_narrow_removal(self):
        gate = self.policy_gate(self.c.source_sha,self.old)
        with self.assertRaisesRegex(ValueError,"publication_held"):
            validate_revision(self.c,self.c.source_sha,gate)
        revision = "e"*40
        validate_revision(self.c,revision,self.policy_gate(revision,self.new))
        with self.assertRaisesRegex(ValueError,"candidate_superseded"):
            validate_revision(self.c,revision,self.policy_gate(revision,self.new,
                [{"filename":"gway_remote/other.py","status":"modified"}]))
        with self.assertRaisesRegex(ValueError,"publication_policy_transition_unverified"):
            validate_revision(self.c,revision,self.policy_gate(revision,self.new+"# extra\n"))

    def test_partial_cannot_pass_full_acceptance(self):
        validate_full_receipt(self.full,self.a,30,self.hosted)
        smoke = smoke_receipt(self.a,30,dict.fromkeys(SMOKE_CHECKS,"pass"))
        for bad in (smoke,dict(self.full,checks={"health":"pass"}),
                    dict(self.full,run_id=31),dict(self.full,screen_restored=False),
                    dict(self.full,physical_checks={}),
                    dict(self.full,hosted_evidence=dict(self.hosted, compose_run=99))):
            with self.assertRaisesRegex(ValueError,"full_acceptance_missing"):
                validate_full_receipt(bad,self.a,30,self.hosted)

    def release(self,draft=True):
        return {"id":40,"tag_name":self.tag,"target_commitish":self.c.source_sha,
                "draft":draft,"prerelease":False,
                "body":f"Android-Version-Code: {self.c.version_code}\nSource-Commit: {self.c.source_sha}\nAPK-SHA256: {self.digest}\nAcceptance-Run: 30\n",
                "assets":[{"name":"gway-remote.apk","state":"uploaded","digest":"sha256:"+self.digest}]}

    def test_asset_identity(self):
        r = self.release()
        verify_release_asset(self.a,r,draft=True,acceptance_run=30)
        for bad in (dict(r,target_commitish="f"*40),dict(r,assets=[]),dict(r,body=""),
                    dict(r,draft=False),dict(r,body=r["body"].replace("Android-Version-Code: 800\n",""))):
            with self.assertRaises(ValueError):
                verify_release_asset(self.a,bad,draft=True,acceptance_run=30)

    def test_explicit_confirmation_before_preflight(self):
        gate = Mock()
        with self.assertRaisesRegex(ValueError,"explicit_publication_authorization_required"):
            publish_exact(Mock(), self.c, revision=self.c.source_sha, acceptance_run=30,
                          artifact_dir=Path("/unused"),gate=gate,publish_run=40,
                          confirm="PLAN_ONLY",expected_digest=self.digest)
        gate.api.assert_not_called()
        gate.gh.assert_not_called()

    def test_draft_verify_publish_and_reconcile_without_reupload(self):
        gate, ledger = Mock(), Mock()
        gate.OWNER = "arthexis"
        gate.REPO = "arthexis/gway-remote"
        state = {}
        ledger.read.side_effect = lambda _: dict(state)
        ledger.record.side_effect = lambda _, stage, value: state.update({stage:value})
        rows, writes = [], []
        def api(path):
            if path.startswith("actions/runs/"):
                return {"status":"in_progress","run_attempt":1,"actor":{"login":"arthexis"},
                        "triggering_actor":{"login":"arthexis"},
                        "display_title":f"Promote RC 800 {self.digest} acceptance 30"}
            if path.startswith("git/matching-refs/"):
                return [{"ref":"refs/tags/"+self.tag}] if rows and not rows[0]["draft"] else []
            if path.startswith("commits/"):
                return {"sha":self.c.source_sha}
            if path == "releases/latest":
                return rows[0]
            raise AssertionError(path)
        gate.api.side_effect = api
        gate.pages.side_effect = lambda _: list(rows)
        def gh(*args):
            action = args[1]
            if action == "create":
                self.assertEqual(Path(args[3]).read_bytes(),self.data)
                self.assertIn("--draft",args)
                writes.append("draft")
                rows.append(self.release())
            elif action == "download":
                self.assertTrue(rows)
                (Path(args[args.index("--dir")+1])/"gway-remote.apk").write_bytes(self.data)
                writes.append("verify")
            elif action == "edit":
                self.assertEqual(writes[-1],"verify")
                self.assertIn("--latest",args)
                writes.append("publish")
                rows[0]["draft"] = False
            else:
                raise AssertionError(args)
        gate.gh.side_effect = gh
        with tempfile.TemporaryDirectory() as tmp:
            apk = Path(tmp)/"signed.apk"
            apk.write_bytes(self.data)
            with patch("gway_remote.android_rc_promotion.preflight",return_value=(self.a,self.full,apk)), \
                 patch("gway_remote.android_rc_promotion.validate_revision"):
                kw = dict(revision=self.c.source_sha,acceptance_run=30,artifact_dir=apk.parent,
                          gate=gate,confirm=CONFIRM,expected_digest=self.digest)
                first = publish_exact(ledger,self.c,publish_run=41,**kw)
                self.assertEqual(writes,["draft","verify","publish","verify"])
                second = publish_exact(ledger,self.c,publish_run=42,**kw)
                self.assertEqual(first,second)
                self.assertEqual(writes,["draft","verify","publish","verify","verify"])
                self.assertEqual(state["approved"]["approval_run"],41)
                rows.clear()
                with self.assertRaisesRegex(ValueError,"publication_intent_uncertain"):
                    publish_exact(ledger,self.c,publish_run=43,**kw)
                self.assertEqual(writes.count("draft"),1)

    def test_workflows_hold_and_legacy_retirement(self):
        root = Path(__file__).resolve().parents[2]/".github/workflows"
        old = (root/"android.yml").read_text()
        new = (root/"android-release-candidate-promote.yml").read_text()
        self.assertIn(HOLD_LINE,old)
        self.assertIn("LEGACY_ANDROID_PUBLISHER_RETIRED",old)
        self.assertNotIn("\n  publish:",old)
        self.assertNotIn("GWAY_APK_KEYSTORE",old)
        self.assertIn("default: PLAN_ONLY",new)
        self.assertIn("github.triggering_actor == 'arthexis'",new)
        self.assertIn("inputs.confirmation == 'PUBLISH_EXACT_ACCEPTED_APK'",new)
        self.assertNotIn("gradle",new)
        self.assertNotIn("secrets.",new)
