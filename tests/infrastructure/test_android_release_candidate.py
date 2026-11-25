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
