import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock

from gway_remote.android_release_candidate import Candidate
from gway_remote.android_rc_contracts import CASES, GROUPS, from_junit, receipt, reconcile, successful_run


class ContractEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.c = Candidate("a"*40, "b"*40, 801, "0.2.801")

    def write(self, root, *, missing=None, skipped=None, failed=None, duplicate=None):
        suite = ET.Element("testsuite")
        for case in sorted(CASES):
            if case == missing:
                continue
            cls, name = case.rsplit(".",1)
            row = ET.SubElement(suite,"testcase",classname=cls,name=name)
            if case == skipped:
                ET.SubElement(row,"skipped")
            if case == failed:
                ET.SubElement(row,"failure")
            if case == duplicate:
                ET.SubElement(suite,"testcase",classname=cls,name=name)
        ET.ElementTree(suite).write(root/"TEST-contract.xml",encoding="utf-8")

    def test_only_actual_named_passes_produce_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root)
            result = from_junit(root,self.c.source_sha,self.c.source_tree,30)
            self.assertEqual(result, receipt(self.c.source_sha,self.c.source_tree,30))
            self.assertEqual(result["groups"],dict.fromkeys(GROUPS,"pass"))

    def test_missing_skipped_failed_and_duplicate_fail_closed(self):
        case = sorted(CASES)[0]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for failure in ("missing","skipped","failed","duplicate"):
                self.write(root,**{failure:case})
                with self.subTest(failure=failure), self.assertRaises(ValueError):
                    from_junit(root,self.c.source_sha,self.c.source_tree,30)
            (root/"TEST-contract.xml").write_text('<!DOCTYPE testsuite [<!ENTITY x "fixture">]><testsuite/>')
            with self.assertRaisesRegex(ValueError,"invalid_contract_report"):
                from_junit(root,self.c.source_sha,self.c.source_tree,30)

    def gate(self, *, bad_actor=False, expired=False, tamper=False, skipped_job=False):
        gate = Mock()
        gate.OWNER = "arthexis"
        def api(path):
            if path.endswith("/jobs?per_page=100"):
                n = int(path.split("/")[2])
                job = {31:"CI",32:"compose-ui",33:"build"}[n]
                return {"total_count":1,"jobs":[{"name":job,"conclusion":"skipped" if skipped_job else "success"}]}
            if path.startswith("actions/runs/") and "/artifacts" not in path:
                return {"run_attempt":1,"status":"completed","conclusion":"success",
                        "actor":{"login":"other" if bad_actor else "arthexis"},
                        "triggering_actor":{"login":"arthexis"}}
            if path.endswith("/artifacts?per_page=100"):
                return {"total_count":1,"artifacts":[{"name":"android-rc-contract-32","id":34,"expired":expired}]}
            if path == "actions/artifacts/34":
                return {"name":"android-rc-contract-32","expired":expired,
                        "workflow_run":{"id":32,"head_sha":self.c.source_sha}}
            raise AssertionError(path)
        gate.api.side_effect = api
        def download(run_id, name, root):
            payload = receipt(self.c.source_sha,self.c.source_tree,32)
            if tamper:
                payload["cases"] = []
            (Path(root)/"contracts.json").write_text(json.dumps(payload))
        gate.download.side_effect = download
        return gate

    def test_reconcile_exact_workflows_and_artifact(self):
        gate = self.gate()
        result = reconcile(gate,self.c,ci_run=31,compose_run=32,build_run=33)
        self.assertEqual(result["contract_artifact_id"],34)
        self.assertEqual(result["hosted_groups"],dict.fromkeys(GROUPS,"pass"))
        expected = [("ci.yml",31),("android-release-candidate.yml",33),("android-compose-ui.yml",32)]
        self.assertEqual([(c.args[1],c.args[2]) for c in gate.verify_run_identity.call_args_list],expected)
        self.assertTrue(all(c.args[3:] == ("workflow_dispatch",self.c.source_sha)
                            for c in gate.verify_run_identity.call_args_list))

    def test_reject_untrusted_jobs_and_tampered_artifact(self):
        for failure in ("bad_actor","expired","tamper","skipped_job"):
            gate = self.gate(**{failure:True})
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                reconcile(gate,self.c,ci_run=31,compose_run=32,build_run=33)
        with self.assertRaisesRegex(ValueError,"evidence_run_conflict"):
            reconcile(self.gate(),self.c,ci_run=31,compose_run=31,build_run=33)
