import unittest
from dataclasses import replace
from gway_remote.android_release_candidate import Candidate, SignedArtifact


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.c = Candidate("a"*40, "b"*40, 800, "0.2.800")
        self.a = SignedArtifact(self.c, "c"*64, "d"*64, 10, 20)
        self.install = dict(installed_digest="c"*64, installed_certificate="d"*64,
                            installed_version=800, device="gway-001",
                            credential_before=True, credential_after=True,
                            expected_certificate="d"*64)
        self.promote = dict(accepted_digest="c"*64, accepted_candidate_id=self.c.candidate_id,
                            accepted_device="gway-001", approved=True, publication_hold=False,
                            current_main="a"*40, downloaded_digest="c"*64)

    def test_identity_and_version_floor(self):
        self.assertEqual(self.c.candidate_id, replace(self.c).candidate_id)
        self.assertNotEqual(self.c.candidate_id, replace(self.c, source_tree="e"*40).candidate_id)
        self.c.require_newer_than(798, 799)
        for floors in ((800, 799), (799, 801), (None, 799)):
            with self.assertRaises(ValueError):
                self.c.require_newer_than(*floors)

    def test_install_evidence(self):
        self.a.validate_install(**self.install)
        for key, value in (("installed_digest","e"*64), ("installed_certificate","e"*64),
                           ("installed_version",799), ("device","other"),
                           ("credential_before",False), ("credential_after",False),
                           ("expected_certificate","e"*64)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.a.validate_install(**{**self.install,key:value})

    def test_promotion_exact_bytes_and_hold(self):
        self.a.validate_promotion(**self.promote)
        for key,value in (("publication_hold",True), ("approved",False),
                          ("accepted_device","other"), ("current_main","e"*40),
                          ("accepted_candidate_id","e"*64), ("accepted_digest","e"*64),
                          ("downloaded_digest","e"*64)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.a.validate_promotion(**{**self.promote,key:value})

    def test_workflow_trust_boundary(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[2] / ".github/workflows"
        build = (root / "android-release-candidate.yml").read_text()
        sign = (root / "android-release-candidate-sign.yml").read_text()
        for workflow in (build, sign):
            self.assertIn("workflow_dispatch:", workflow)
            self.assertIn("github.ref == 'refs/heads/main'", workflow)
            self.assertIn("github.triggering_actor == 'arthexis'", workflow)
            self.assertNotIn("gh release create", workflow)
            self.assertNotIn("contents: write", workflow)
        self.assertNotIn("secrets.", build)
        self.assertIn(":app:assembleRelease", build)
        self.assertIn("app-release-unsigned.apk", build)
        self.assertNotIn("actions/checkout", sign)
        self.assertNotIn("gradle", sign)
        self.assertIn("environment: android-release-signing", sign)
        self.assertIn('"$ENABLED" == true', sign)
        self.assertIn("RC_APPROVED_ARTIFACT_ID", sign)
        self.assertIn("RC_PRODUCTION_CERT_SHA256", sign)
        self.assertIn("GWAY_APK_KEYSTORE_BASE64", sign)
        self.assertLess(sign.index("Verify explicit candidate authorization"), sign.index("secrets.GWAY_APK_KEYSTORE_BASE64"))

    def test_durable_ledger(self):
        import tempfile
        from pathlib import Path
        from gway_remote.android_release_candidate import CandidateLedger
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.sqlite"
            ledger = CandidateLedger(path)
            try:
                self.assertTrue(ledger.allocate(self.c, published_version=798, installed_version=799))
                self.assertFalse(ledger.allocate(self.c, published_version=798, installed_version=799))
                with self.assertRaises(ValueError):
                    ledger.allocate(replace(self.c, source_tree="f"*40), published_version=798, installed_version=799)
                with self.assertRaises(ValueError):
                    ledger.record(self.c.candidate_id, "signed", {"digest":"c"*64})
                self.assertTrue(ledger.record(self.c.candidate_id, "built", {"run":100}))
                self.assertFalse(ledger.record(self.c.candidate_id, "built", {"run":100}))
                with self.assertRaises(ValueError):
                    ledger.record(self.c.candidate_id, "built", {"run":101})
            finally:
                ledger.close()
            ledger = CandidateLedger(path)
            try:
                self.assertEqual(ledger.read(self.c.candidate_id)["built"], {"run":100})
                self.assertTrue(ledger.record(self.c.candidate_id, "signed", {"digest":"c"*64}))
            finally:
                ledger.close()

    def test_dispatch_resume_and_uncertainty(self):
        from unittest.mock import Mock
        from gway_remote.android_release_candidate import CandidateLedger, dispatch_candidate
        ledger = CandidateLedger(":memory:")
        gate = Mock()
        gate.api.return_value = {"commit":{"sha":self.c.source_sha}}
        gate.create_run.return_value = 123
        gate.await_dispatch_visibility.side_effect = RuntimeError("not visible")
        try:
            ledger.allocate(self.c, published_version=798, installed_version=799)
            with self.assertRaisesRegex(RuntimeError, "not visible"):
                dispatch_candidate(ledger, self.c, "built", gate=gate)
            gate.await_dispatch_visibility.side_effect = None
            self.assertEqual(dispatch_candidate(ledger, self.c, "built", gate=gate),123)
            gate.create_run.assert_called_once()
            gate.await_dispatch_visibility.assert_called_with("android-release-candidate.yml",123,self.c.source_sha)
            ledger.record(self.c.candidate_id,"built",{"run_id":123,"artifact_id":234})
            gate.create_run.side_effect = TimeoutError("uncertain")
            with self.assertRaises(TimeoutError):
                dispatch_candidate(ledger,self.c,"signed",artifact_id=234,build_run_id=123,gate=gate)
            with self.assertRaisesRegex(ValueError,"dispatch_uncertain"):
                dispatch_candidate(ledger,self.c,"signed",artifact_id=234,build_run_id=123,gate=gate)
            self.assertEqual(gate.create_run.call_count,2)
            with self.assertRaisesRegex(ValueError,"build_evidence_mismatch"):
                dispatch_candidate(ledger,self.c,"signed",artifact_id=235,build_run_id=123,gate=gate)
        finally:
            ledger.close()

    def test_lab_upgrade_plan(self):
        from gway_remote.android_release_candidate import plan_lab_install
        installed = dict(package=self.c.package, apk_sha256="e"*64,
                         certificate_sha256="d"*64, version_code=799)
        args = dict(installed=installed,pinned_certificate="d"*64,device="gway-001",
                    lab_authorized=True,credential_present=True,screen_unlocked=True)
        self.assertEqual(plan_lab_install(self.a,**args),"incremental_update")
        same = dict(installed,apk_sha256="c"*64,version_code=800)
        self.assertEqual(plan_lab_install(self.a,**{**args,"installed":same}),"verify_noop")
        for key,value in (("lab_authorized",False),("screen_unlocked",None),
                          ("credential_present",False),("device","other"),
                          ("installed",None),("pinned_certificate","e"*64)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                plan_lab_install(self.a,**{**args,key:value})
        for evidence in (dict(installed,version_code=800),
                         dict(installed,version_code=801),
                         dict(installed,certificate_sha256="e"*64),
                         dict(same,version_code=799)):
            with self.assertRaises(ValueError):
                plan_lab_install(self.a,**{**args,"installed":evidence})

    def test_promotion_plan(self):
        from gway_remote.android_release_candidate import plan_promotion
        self.assertEqual(plan_promotion(self.a,existing_release=None,**self.promote),
                         "create_exact_release")
        existing = dict(source_sha=self.c.source_sha,tag="android-v0.2.800",
                        apk_sha256="c"*64,certificate_sha256="d"*64)
        self.assertEqual(plan_promotion(self.a,existing_release=existing,**self.promote),
                         "verify_noop")
        for key,value in (("source_sha","e"*40),("tag","android-v0.2.801"),
                          ("apk_sha256","e"*64),("certificate_sha256","e"*64)):
            with self.assertRaises(ValueError):
                plan_promotion(self.a,existing_release={**existing,key:value},**self.promote)
