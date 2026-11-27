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
        self.assertNotIn("openssl cms", sign)
        self.assertNotIn("TRANSPORT_CERT", sign)
        self.assertIn('--out "$DEST/gway-remote.apk"', sign)
        self.assertIn("RC_APPROVED_SOURCE_SHA", sign)
        self.assertIn("RC_APPROVED_WORKFLOW_SHA", sign)
        self.assertIn("RC_REFERENCE_APK_SHA256", sign)
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

    def test_reconcile_build_from_exact_run(self):
        from dataclasses import asdict
        from pathlib import Path
        from unittest.mock import Mock
        from gway_remote.android_release_candidate import CandidateLedger, dispatch_candidate, reconcile_artifact
        import hashlib
        import json
        ledger = CandidateLedger(":memory:")
        gate = Mock(OWNER="arthexis", REPO="arthexis/gway-remote")
        artifact = b"unsigned candidate bytes"
        digest = hashlib.sha256(artifact).hexdigest()
        manifest = {**asdict(self.c),"repository":gate.REPO,"build_run_id":123,"unsigned_sha256":digest}
        def api(path):
            if path == "branches/main":
                return {"commit":{"sha":self.c.source_sha}}
            self.assertEqual(path,"actions/runs/123/artifacts?per_page=100")
            return {"total_count":1,"artifacts":[{"name":"unsigned-release-candidate-123","id":234,"expired":False}]}
        def download(run,name,directory):
            self.assertEqual((run,name),(123,"unsigned-release-candidate-123"))
            (Path(directory)/"gway-remote-unsigned.apk").write_bytes(artifact)
            (Path(directory)/"manifest.json").write_text(json.dumps(manifest))
        gate.api.side_effect = api
        gate.download.side_effect = download
        gate.create_run.return_value = 123
        gate.wait_run.return_value = {"actor":{"login":"arthexis"},"triggering_actor":{"login":"arthexis"}}
        try:
            ledger.allocate(self.c,published_version=798,installed_version=799)
            dispatch_candidate(ledger,self.c,"built",gate=gate)
            manifest["source_tree"]="e"*40
            with self.assertRaisesRegex(ValueError,"manifest_mismatch"):
                reconcile_artifact(ledger,self.c,"built",gate=gate)
            self.assertNotIn("built",ledger.read(self.c.candidate_id))
            manifest["source_tree"]=self.c.source_tree
            expected={"run_id":123,"artifact_id":234,"unsigned_sha256":digest}
            self.assertEqual(reconcile_artifact(ledger,self.c,"built",gate=gate),expected)
            self.assertEqual(reconcile_artifact(ledger,self.c,"built",gate=gate),expected)
            gate.create_run.assert_called_once()
            gate.wait_run.assert_called_with("android-release-candidate.yml",123,"workflow_dispatch",self.c.source_sha)
        finally:
            ledger.close()


    def test_signing_revision_allows_only_delivery_fix(self):
        from unittest.mock import Mock
        from gway_remote.android_release_candidate import validate_signing_revision
        gate = Mock()
        revision = "e"*40
        comparison = {"status":"ahead","merge_base_commit":{"sha":self.c.source_sha},
                      "total_commits":2,"files":[{"filename":"gway_remote/android_release_candidate.py","status":"modified"}]}
        tree = {"tree":[{"path":"android","type":"tree","sha":"f"*40}]}
        gate.api.side_effect = [comparison,tree,tree]
        validate_signing_revision(self.c,revision,gate)
        for bad in ("android/app/build.gradle.kts","gway_remote/mcp_http.py"):
            gate.api.side_effect = [dict(comparison,files=[{"filename":bad,"status":"modified"}])]
            with self.assertRaisesRegex(ValueError,"candidate_superseded"):
                validate_signing_revision(self.c,revision,gate)
        gate.api.side_effect = [comparison,tree,{"tree":[{"path":"android","type":"tree","sha":"a"*40}]}]
        with self.assertRaisesRegex(ValueError,"android_tree_changed"):
            validate_signing_revision(self.c,revision,gate)

    def test_exact_artifact_persistence_and_replay(self):
        import hashlib
        import tempfile
        from pathlib import Path
        from gway_remote.android_release_candidate import persist_private_apk
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            destination = root / "artifacts"
            destination.mkdir(mode=0o700)
            raw = root / "original.apk"
            raw.write_bytes(b"exact signed candidate test bytes")
            digest = hashlib.sha256(raw.read_bytes()).hexdigest()
            persist_private_apk(raw,destination,self.c.candidate_id,digest)
            persist_private_apk(raw,destination,self.c.candidate_id,digest)
            saved = destination/f"{self.c.candidate_id}.apk"
            self.assertEqual(saved.read_bytes(),raw.read_bytes())
            self.assertEqual(saved.stat().st_mode & 0o777,0o600)
            with self.assertRaisesRegex(ValueError,"private_artifact_digest_mismatch"):
                persist_private_apk(raw,destination,self.c.candidate_id,"e"*64)
            saved.write_bytes(b"conflict")
            with self.assertRaisesRegex(ValueError,"private_artifact_conflict"):
                persist_private_apk(raw,destination,self.c.candidate_id,digest)

    def test_signing_workflow_yaml_and_shell_syntax(self):
        import subprocess
        from pathlib import Path
        from textwrap import dedent
        root = Path(__file__).resolve().parents[2]
        content = (root/".github/workflows/android-release-candidate-sign.yml").read_text()
        lines = content.splitlines()
        self.assertTrue(all(not line or line.startswith("    ") or
                            line in ("permissions:", "concurrency:", "jobs:", "on:") or
                            line.startswith(("name:", "  ")) for line in lines))
        self.assertEqual(sum(line.startswith("      - ") for line in lines),3)
        starts = [i for i,line in enumerate(lines) if line == "        run: |"]
        self.assertEqual(len(starts),2)
        for start in starts:
            end = start + 1
            while end < len(lines) and (not lines[end] or lines[end].startswith("          ")):
                end += 1
            script = dedent("\n".join(lines[start+1:end])) + "\n"
            result = subprocess.run(["bash","-n"],input=script,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(content.count("retention-days: 30"),1)
        self.assertIn('path: ${{ runner.temp }}/signed-release-candidate/',content)
        try:
            import yaml
        except ImportError:
            # The dependency-free CI suite still checks the exact block layout
            # and Bash syntax; full YAML parsing is also run on the lab host.
            return
        workflow = yaml.safe_load(content)
        self.assertEqual(set(workflow["jobs"]), {"sign"})
        self.assertEqual(len(workflow["jobs"]["sign"]["steps"]),3)


    def test_live_health_gate(self):
        from gway_remote.android_release_candidate import health_is_authenticated
        tree = {"truncated":False,"elements":[{"text":"API health"},{"text":'{"status":"ok","api":"gway-remote/v1"}'}]}
        self.assertTrue(health_is_authenticated(tree))
        actual = {"truncated":False,"elements":[{"text":"System"},{"text":"API Health"},
                  {"text":"API health"},{"text":"status: ok"},{"text":"api: gway-remote/v1"}]}
        self.assertTrue(health_is_authenticated(actual))
        for bad in ("status: failed", "api: other", "status: ok", "Token is required"):
            self.assertFalse(health_is_authenticated(dict(actual, elements=actual["elements"]+[{"text":bad}])))
        self.assertFalse(health_is_authenticated(dict(actual,elements=actual["elements"][:-1])))
        self.assertFalse(health_is_authenticated(dict(actual,truncated=True)))
        for invalid in (
            dict(tree,truncated=True),
            {"truncated":False,"elements":[{"text":"API health"},{"text":"Token is required"}]},
            {"truncated":False,"elements":[{"text":'{"status":"ok","api":"gway-remote/v1"}'}]},
            {"truncated":False,"elements":[{"text":"API health"},{"text":'{"status":"ok"}'}]},
        ):
            self.assertFalse(health_is_authenticated(invalid))

    def test_stable_installer_preflight_update_and_replay(self):
        import hashlib
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from gway_remote.android_release_candidate import CandidateLedger, install_stable_candidate
        from gway_remote.android_canary_install import CANARY, PRODUCTION
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o700)
            apk = root/f"{self.c.candidate_id}.apk"
            apk.write_bytes(b"x"*12000)
            apk.chmod(0o600)
            digest = hashlib.sha256(apk.read_bytes()).hexdigest()
            signed = {"artifact_id":10,"run_id":20,"apk_sha256":digest,
                      "certificate_sha256":"d"*64,"workflow_sha":"e"*40}
            ledger = CandidateLedger(":memory:")
            gate = Mock(OWNER="arthexis")
            revision = "f"*40
            run = {"id":30,"path":".github/workflows/android-release-candidate-install.yml",
                   "event":"workflow_dispatch","head_branch":"main","head_sha":revision,
                   "status":"in_progress","run_attempt":1,"actor":{"login":"arthexis"},
                   "triggering_actor":{"login":"arthexis"}}
            sign = dict(run,path=".github/workflows/android-release-candidate-sign.yml",
                        head_sha="e"*40,conclusion="success")
            meta = {"expired":False,"name":"signed-release-candidate-20",
                    "workflow_run":{"id":20,"head_sha":"e"*40}}
            def api(path):
                return {"actions/runs/30":run,"actions/runs/20":sign,
                        "actions/artifacts/10":meta,"branches/main":{"commit":{"sha":revision}}}[path]
            gate.api.side_effect = api
            device = Mock()
            device.screen_state.return_value = {"screen_on":True,"locked":False}
            device.ui_tree.return_value = {"truncated":False,"elements":[{"text":"API health"},{"text":"Token is required"}]}
            before = dict(package=PRODUCTION,apk_sha256="b"*64,certificate_sha256="d"*64,version_code=799)
            after = dict(before,apk_sha256=digest,version_code=800)
            inspect = Mock(return_value=before)
            calls = []
            def call(argv, timeout):
                calls.append(argv)
                if argv[3:7] == ["shell","pm","path",CANARY]:
                    return SimpleNamespace(returncode=0,stdout="package:/data/app/canary/base.apk",stderr="")
                if argv[3:5] == ["install","-r"]:
                    self.assertEqual(argv[5],str(apk))
                    inspect.return_value = after
                    return SimpleNamespace(returncode=0,stdout="Success",stderr="")
                self.fail("unexpected USB operation")
            kwargs = dict(artifact_dir=root,workflow_sha=revision,install_run_id=30,
                          expected_digest=digest,expected_certificate="d"*64,expected_artifact_id=10,
                          gate=gate,call=call,device=device,inspect=inspect,hostname="gway-001")
            try:
                ledger.allocate(self.c,published_version=798,installed_version=799)
                ledger.record(self.c.candidate_id,"built",{"run_id":19,"artifact_id":9})
                ledger.record(self.c.candidate_id,"signed",signed)
                with patch("gway_remote.android_release_candidate.validate_install_revision"), \
                     patch("gway_remote.android_release_candidate.validate_signing_revision"), \
                     patch("gway_remote.android_canary_install.authorized_usb",return_value="LAB"), \
                     patch("gway_remote.android_canary_certificate.certificate_sha256",return_value="d"*64):
                    blocked = install_stable_candidate(ledger,self.c,preflight_only=True,**kwargs)
                    self.assertEqual(blocked["status"],"blocked")
                    with self.assertRaisesRegex(ValueError,"credential_missing_or_unverified"):
                        install_stable_candidate(ledger,self.c,**kwargs)
                    self.assertEqual(calls,[])
                    self.assertNotIn("installed",ledger.read(self.c.candidate_id))
                    with self.assertRaisesRegex(ValueError,"lab_only_authorization_mismatch"):
                        install_stable_candidate(ledger,self.c,allow_unverified_auth=True,**kwargs)
                    self.assertEqual(calls,[])
                    run["display_title"] = "Android RC install-lab-only version 800 artifact 10"
                    receipt = install_stable_candidate(ledger,self.c,allow_unverified_auth=True,**kwargs)
                    self.assertFalse(receipt["credential_before"])
                    self.assertTrue(receipt["installation_without_verified_auth"])
                    self.assertEqual(receipt["authenticated_acceptance"],"pending")
                    self.assertEqual(receipt["installed_after"],after)
                    self.assertEqual(receipt["status"],"installed")
                    self.assertTrue(receipt["canary_path_unchanged"])
                    self.assertEqual(install_stable_candidate(ledger,self.c,allow_unverified_auth=True,**kwargs),receipt)
                    self.assertEqual(sum(x[3:5]==["install","-r"] for x in calls),1)
                    self.assertNotIn("accepted",ledger.read(self.c.candidate_id))
                    from unittest.mock import Mock
                    with self.assertRaisesRegex(ValueError,"upgrade_health_unverified_reconcile"):
                        install_stable_candidate(ledger,self.c,fresh_check=Mock(return_value=True),**kwargs)
                    self.assertIsNone(ledger.read_upgrade_health(self.c.candidate_id))
                    self.assertEqual(sum(x[3:5]==["install","-r"] for x in calls),1)
                    for post in (False, True):
                        # Separate hermetic fixture for an authenticated incremental update.
                        other = CandidateLedger(":memory:")
                        try:
                            other.allocate(self.c,published_version=798,installed_version=799)
                            other.record(self.c.candidate_id,"built",{"run_id":19,"artifact_id":9})
                            other.record(self.c.candidate_id,"signed",signed)
                            inspect.return_value = before
                            calls.clear()
                            check = Mock(side_effect=[True, post])
                            result = install_stable_candidate(other,self.c,fresh_check=check,**kwargs)
                            self.assertEqual(check.call_count,2)
                            self.assertEqual(sum(x[3:5]==["install","-r"] for x in calls),1)
                            self.assertIn("installed",other.read(self.c.candidate_id))
                            self.assertEqual(result["status"],"installed" if post else "blocked")
                            self.assertEqual(other.read_upgrade_health(self.c.candidate_id) is not None,post)
                            if not post:
                                with self.assertRaisesRegex(ValueError,"upgrade_health_unverified_reconcile"):
                                    install_stable_candidate(other,self.c,fresh_check=Mock(return_value=True),**kwargs)
                                self.assertEqual(sum(x[3:5]==["install","-r"] for x in calls),1)
                        finally:
                            other.close()
            finally:
                ledger.close()

    def test_stable_workflow_is_manual_and_shared_hardware_group(self):
        from pathlib import Path
        workflow = (Path(__file__).resolve().parents[2]/".github/workflows/android-release-candidate-install.yml").read_text()
        self.assertIn("workflow_dispatch:",workflow)
        self.assertIn("group: gway-001-android-canary-install",workflow)
        self.assertIn("cancel-in-progress: false",workflow)
        self.assertIn("github.actor == 'arthexis'",workflow)
        self.assertIn("github.triggering_actor == 'arthexis'",workflow)
        self.assertIn("github.ref == 'refs/heads/main'",workflow)
        self.assertIn("default: preflight",workflow)
        self.assertIn("install-lab-only) args+=(--allow-unverified-auth)",workflow)
        self.assertNotIn("secrets.",workflow)
        self.assertNotIn("assembleRelease",workflow)
        self.assertNotIn("gh release create",workflow)
        self.assertNotIn("uninstall",workflow)

    def test_install_revision_exact_main(self):
        from unittest.mock import Mock
        from gway_remote.android_release_candidate import validate_install_revision
        gate = Mock()
        gate.api.side_effect = lambda path: {
            "branches/main": {"commit": {"sha": self.c.source_sha}},
            f"git/commits/{self.c.source_sha}": {"tree": {"sha": self.c.source_tree}},
        }[path]
        validate_install_revision(self.c, self.c.source_sha, gate)
        with self.assertRaisesRegex(ValueError, "source_tree_mismatch"):
            validate_install_revision(replace(self.c, source_tree="f"*40), self.c.source_sha, gate)
        with self.assertRaisesRegex(ValueError, "candidate_superseded"):
            validate_install_revision(self.c, "f"*40, gate)

    def test_reconciliation_checkpoint_is_not_admission(self):
        import base64
        import hashlib
        import tempfile
        from pathlib import Path
        from unittest.mock import Mock, patch
        from gway_remote.android_release_candidate import CandidateLedger, reconciliation_status
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o700)
            apk = root / f"{self.c.candidate_id}.apk"
            apk.write_bytes(b"x"*12000)
            apk.chmod(0o600)
            ledger = CandidateLedger(":memory:")
            try:
                ledger.allocate(self.c, published_version=798, installed_version=799)
                ledger.record(self.c.candidate_id, "built", {"run_id": 10})
                ledger.record(self.c.candidate_id, "signed", {
                    "apk_sha256": hashlib.sha256(apk.read_bytes()).hexdigest(),
                    "certificate_sha256": "d"*64, "artifact_id": 11, "run_id": 20})
                ledger.record(self.c.candidate_id, "installed", {"credential_before": False})
                previous = ledger.read(self.c.candidate_id)
                gate = Mock()
                gate.api.side_effect = lambda path: {
                    "branches/main": {"commit": {"sha": "f"*40}},
                    f"contents/.github/workflows/android.yml?ref={'f'*40}": {
                        "encoding": "base64",
                        "content": base64.b64encode(b"ANDROID_PUBLICATION_HOLD_718").decode()},
                }[path]
                with patch("gway_remote.android_canary_certificate.certificate_sha256", return_value="d"*64):
                    result = reconciliation_status(ledger, self.c, artifact_dir=root, gate=gate)
                    self.assertTrue(result["local_signed_artifact_verified"])
                    self.assertFalse(result["admission"])
                    self.assertEqual(result["blockers"], [
                        "candidate_superseded", "authenticated_upgrade_baseline_missing",
                        "authenticated_acceptance_missing", "publication_approval_missing", "publication_held"])
                    apk.write_bytes(b"y"*12000)
                    tampered = reconciliation_status(ledger, self.c, artifact_dir=root, gate=gate)
                    self.assertFalse(tampered["local_signed_artifact_verified"])
                    self.assertIn("signed_artifact_unverified", tampered["blockers"])
                self.assertEqual(ledger.read(self.c.candidate_id), previous)
            finally:
                ledger.close()

    def test_read_only_ledger_never_creates_or_writes(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        from gway_remote.android_release_candidate import CandidateLedger
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.sqlite"
            with self.assertRaises(sqlite3.OperationalError):
                CandidateLedger(path, read_only=True)
            self.assertFalse(path.exists())
            ledger = CandidateLedger(path)
            ledger.allocate(self.c, published_version=798, installed_version=799)
            ledger.close()
            ledger = CandidateLedger(path, read_only=True)
            try:
                self.assertIn("allocated", ledger.read(self.c.candidate_id))
                with self.assertRaises(sqlite3.OperationalError):
                    ledger.record(self.c.candidate_id, "built", {"run_id": 10})
                self.assertNotIn("built", ledger.read(self.c.candidate_id))
            finally:
                ledger.close()

    def test_upgrade_health_is_not_module_acceptance_or_retroactive_baseline(self):
        from gway_remote.android_release_candidate import CandidateLedger, PACKAGE
        for prior_auth in (False, True):
            ledger = CandidateLedger(":memory:")
            try:
                ledger.allocate(self.c, published_version=798, installed_version=799)
                ledger.record(self.c.candidate_id, "built", {"run_id": 19})
                ledger.record(self.c.candidate_id, "signed", {"run_id":20,"artifact_id":10,
                              "apk_sha256":"c"*64,"certificate_sha256":"d"*64})
                before = dict(package=PACKAGE, version_code=799, apk_sha256="e"*64, certificate_sha256="d"*64)
                after = dict(before, version_code=800, apk_sha256="c"*64)
                ledger.record(self.c.candidate_id, "installed", {
                    "candidate_id": self.c.candidate_id, "artifact_id":10,
                    "apk_sha256":"c"*64,"certificate_sha256":"d"*64,
                    "operation":"incremental_update","device":"gway-001","install_run_id":30,
                    "credential_before":prior_auth,"canary_path_unchanged":True,
                    "installed_before":before,"installed_after":after})
                with self.assertRaisesRegex(ValueError,"post_install_authentication_failed"):
                    ledger.record_upgrade_health(self.c, run_id=30, post_authenticated=False)
                with self.assertRaisesRegex(ValueError,"upgrade_baseline_unverified"):
                    ledger.record_upgrade_health(self.c, run_id=31, post_authenticated=True)
                self.assertIsNone(ledger.read_upgrade_health(self.c.candidate_id))
                if prior_auth:
                    receipt = ledger.record_upgrade_health(self.c, run_id=30, post_authenticated=True)
                    self.assertEqual(receipt["from_version"],799)
                    self.assertEqual(receipt["to_version"],800)
                    self.assertEqual(receipt,ledger.record_upgrade_health(self.c,run_id=30,post_authenticated=True))
                    self.assertEqual(receipt,ledger.read_upgrade_health(self.c.candidate_id))
                else:
                    with self.assertRaisesRegex(ValueError,"upgrade_baseline_unverified"):
                        ledger.record_upgrade_health(self.c,run_id=30,post_authenticated=True)
                self.assertNotIn("accepted",ledger.read(self.c.candidate_id))
            finally:
                ledger.close()
