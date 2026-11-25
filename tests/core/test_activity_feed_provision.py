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

    def test_failed_delivery_preserves_old_pointer(self):
        if os.geteuid()==0: self.skipTest("installation owner test requires nonroot")
        with TemporaryDirectory() as temp:
            home=Path(temp)
            n.install("gway-001",ROOT,TOKEN,home=home,publisher=lambda cfg:lambda value:"delivered")
            other="d"*24
            with self.assertRaises(RuntimeError):
                n.install("gway-001",ROOT,"gwr_"+other+"_"+"y"*43,home=home,
                          publisher=lambda cfg:lambda value:"retry")
            self.assertEqual(n.status("gway-001",home=home)["credential_id"],CHILD)
            self.assertFalse((home/".config/gway-remote"/("feed-token-"+other)).exists())

    def test_rotation_uses_existing_principal_and_revokes_old_after_ack(self):
        policy=p.grant("gway-001",["arthexis/gway-remote"])
        old="d"*24
        calls=[]
        def child(account,action,payload):
            calls.append((action,payload.get("principal"),payload.get("id")))
            if action=="status": return {"configured":True,"principal":ROOT,"credential_id":old}
            if action=="issue": return {"principal":ROOT,"credential":TOKEN}
            if action=="install": return {"configured":True,"principal":ROOT,"credential_id":CHILD,"delivered":True}
            return {"verified":True}
        result=p.provision("gway-001",["arthexis/gway-remote"],30,child=child,read=lambda:{ROOT:policy},
                           save=lambda grants:self.fail("rotation must preserve grant"))
        self.assertTrue(result["rotation"])
        self.assertEqual(calls,[("status",None,None),("check-child",ROOT,old),("issue",ROOT,None),("install",ROOT,None),("revoke",ROOT,old)])

    def test_revocation_checks_actual_registry_lineage_and_scope(self):
        from gway_remote.mcp_bearer import BearerRegistry
        with TemporaryDirectory() as temp:
            registry=BearerRegistry(Path(temp)/"auth.sqlite")
            root=registry.issue(scope="gway:feed-publish",operator_approved=True)
            parent=root.split("_",2)[1]
            other=registry.issue(scope="gway:feed-publish",operator_approved=True)
            other_id=other.split("_",2)[1]
            child=registry.issue(scope="gway:feed-publish",parent_id=parent)
            key=child.split("_",2)[1]
            execute=registry.issue(scope="gway:execute",operator_approved=True)
            execute_id=execute.split("_",2)[1]
            for principal, target in ((parent,parent),(other_id,key),(parent,execute_id)):
                with self.assertRaises(PermissionError):
                    p.check_child(registry,principal,target,revoke=True)
            self.assertTrue(registry.verify(execute,required_scope="gway:execute"))
            self.assertTrue(registry.verify(child,required_scope="gway:feed-publish"))
            self.assertEqual(p.check_child(registry,parent,key),{"verified":True})
            p.check_child(registry,parent,key,revoke=True)
            self.assertFalse(registry.verify(child,required_scope="gway:feed-publish"))
            self.assertTrue(registry.verify(root,required_scope="gway:feed-publish"))
            self.assertTrue(registry.verify(other,required_scope="gway:feed-publish"))
