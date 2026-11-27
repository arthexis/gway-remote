import unittest
from unittest.mock import Mock
from pathlib import Path
from gway_remote.android_release_candidate import Candidate, SignedArtifact
from gway_remote.android_rc_acceptance import (SMOKE_CHECKS, FULL_CHECKS, PhysicalSmoke,
    smoke_receipt, validate_smoke_receipt, verify_installed, validate_run,
    verify_deployment_guard, tagged_control_ready)


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.c = Candidate("a"*40, "b"*40, 800, "0.2.800")
        self.a = SignedArtifact(self.c, "c"*64, "d"*64, 10, 20)
        self.r = smoke_receipt(self.a, 30, dict.fromkeys(SMOKE_CHECKS,"pass"))

    def test_scope_and_identity_fail_closed(self):
        self.assertEqual(validate_smoke_receipt(self.r,self.a,30), self.r)
        self.assertTrue(set(SMOKE_CHECKS) < FULL_CHECKS)
        for key, value in (("scope","authenticated_full_v1"),("status","passed"),
                           ("run_id",31),("artifact_id",11),("version_code",801),
                           ("apk_sha256","e"*64),("source_sha","e"*40),
                           ("publication_admission",True),("canary_unchanged",False),
                           ("screen_restored",False),("checks",{"health":"pass"})):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_smoke_receipt(dict(self.r, **{key:value}), self.a, 30)

    def test_installed_identity_exact(self):
        data = dict(package=self.c.package, version_code=800, apk_sha256="c"*64,
                    certificate_sha256="d"*64)
        verify_installed(self.a,data)
        for key,value in (("package","other"),("version_code",799),
                          ("apk_sha256","e"*64),("certificate_sha256","e"*64)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                verify_installed(self.a,dict(data,**{key:value}))

    def test_stale_candidate_before_run_lookup(self):
        gate = Mock()
        gate.api.return_value = {"commit":{"sha":"e"*40}}
        with self.assertRaisesRegex(ValueError,"candidate_superseded"):
            validate_run(self.c,30,gate,completed=True)
        gate.api.assert_called_once_with("branches/main")
        gate.verify_run_identity.assert_not_called()

    def test_ambiguous_moved_target_never_dispatches(self):
        d = Mock()
        d.serial.return_value = "LAB"
        d.size.return_value = (1080,2220)
        d.screen_state.return_value = {"rotation":0}
        probe = PhysicalSmoke(d,"LAB",pause=lambda _:None)
        row = dict(text="Cerrar",enabled=True,bounds="[10,20][30,40]")
        probe.observe = Mock(return_value={"elements":[row,row]})
        with self.assertRaisesRegex(ValueError,"physical_target_ambiguous"):
            probe.tap("text","Cerrar")
        probe.observe = Mock(side_effect=[{"elements":[row]},
            {"elements":[dict(row,bounds="[20,30][40,50]")]}])
        with self.assertRaisesRegex(ValueError,"physical_target_moved"):
            probe.tap("text","Cerrar")
        d.adb.assert_not_called()

    def test_disabled_deployment_requires_actual_tagged_parent_semantics(self):
        text = {"text":"Deploy all", "enabled":True}
        label = {"text":"Confirm deployment of all repositories", "checked":False}
        confirm = {"resource_id":"rc-deploy-confirm","checkable":True,"checked":False}
        submit = {"resource_id":"rc-deploy-submit","enabled":False}
        verify_deployment_guard({"elements":[text,label,confirm,submit]})
        for rows in ([text,label], [confirm,dict(submit,enabled=True)],
                     [dict(confirm,checked=True),submit],
                     [dict(confirm,checkable=False),submit],[confirm,submit,submit]):
            with self.subTest(rows=rows), self.assertRaisesRegex(ValueError,"deployment_guard_unverified"):
                verify_deployment_guard({"elements":rows})

    def test_feed_ready_requires_unique_actual_enabled_control(self):
        label = {"text":"Actualizar actividad","enabled":True}
        tag = {"resource_id":"rc-feed-refresh","enabled":True}
        self.assertFalse(tagged_control_ready([label],"rc-feed-refresh"))
        self.assertTrue(tagged_control_ready([label,tag],"rc-feed-refresh"))
        self.assertFalse(tagged_control_ready([label,dict(tag,enabled=False)],"rc-feed-refresh"))
        self.assertFalse(tagged_control_ready([tag,tag],"rc-feed-refresh"))

    def test_workflow_restricted_to_reviewed_main(self):
        root = Path(__file__).resolve().parents[2]
        workflow = (root/".github/workflows/android-release-candidate-accept.yml").read_text()
        self.assertIn("github.triggering_actor == 'arthexis'",workflow)
        self.assertIn("github.ref == 'refs/heads/main'",workflow)
        self.assertIn("group: gway-001-android-canary-install",workflow)
        self.assertNotIn("contents: write",workflow)
        self.assertNotIn("secrets.",workflow)
        self.assertNotIn("lab-install",workflow)
