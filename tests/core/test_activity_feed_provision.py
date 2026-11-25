import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from gway_remote import activity_feed_provision as p
from gway_remote import activity_feed_provision_node as n

ROOT="a"*24
CHILD="b"*24
TOKEN="gwr_"+CHILD+"_"+"x"*43

class ProvisionTest(TestCase):
    def test_success_and_exact_scope(self):
        grants={}
        calls=[]
        def child(account,action,payload):
            calls.append(action)
            if action=="status": return {"configured":False}
            if action=="issue": return {"principal":ROOT,"credential":TOKEN}
            if action=="install":
                self.assertEqual(payload["credential"],TOKEN)
                return {"configured":True,"principal":ROOT,"credential_id":CHILD,"delivered":True}
        result=p.provision("gway-001",["arthexis/gway-remote"],30,child=child,read=lambda:grants,save=grants.update)
        self.assertEqual(calls,["status","issue","install"])
        self.assertEqual(grants[ROOT]["nodes"],["gway-001"])
        self.assertNotIn(TOKEN,str(result))
        self.assertEqual(result["scope"],"gway:feed-publish")

    def test_uncertain_install_revokes_only_child(self):
        grants={}
        calls=[]
        def child(account,action,payload):
            if action=="status": return {"configured":False}
            if action=="issue": return {"principal":ROOT,"credential":TOKEN}
            if action=="install": raise RuntimeError("uncertain")
            calls.append(payload["id"])
        with self.assertRaises(RuntimeError):
            p.provision("gway-001",["arthexis/gway-remote"],30,child=child,read=lambda:grants,save=grants.update)
        self.assertEqual(calls,[CHILD])
        self.assertIn(ROOT,grants)

    def test_node_private_pointer_after_verified_delivery(self):
        if os.geteuid()==0: self.skipTest("installation owner test requires nonroot")
        with TemporaryDirectory() as temp:
            home=Path(temp)
            def publisher(cfg):
                self.assertEqual(Path(cfg["token_file"]).stat().st_mode & 0o777,0o600)
                return lambda value:"delivered"
            result=n.install("gway-001",ROOT,TOKEN,home=home,publisher=publisher)
            self.assertTrue(result["delivered"])
            self.assertEqual(n.status("gway-001",home=home)["credential_id"],CHILD)
            self.assertEqual((home/".config/gway-remote/feed.json").stat().st_mode & 0o777,0o600)
            with self.assertRaises(PermissionError):
                n.install("gway-001","c"*24,TOKEN,home=home,publisher=publisher)

    def test_wrong_policy_and_noninteractive_console(self):
        with self.assertRaises(ValueError): p.grant("gway-001",["arthexis/*"])
        with patch.object(p.sys.stdin,"isatty",return_value=False):
            self.assertEqual(p.main(["gway-001","--repository","arthexis/gway-remote"]),1)
