import importlib.util
import hashlib
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("deploy_aeon", ROOT / "scripts/deploy-aeon-score.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)

class AeonDeploymentTests(unittest.TestCase):
    def test_exact_main_and_ci(self):
        sha = "a"*40
        deploy.checked_revision(sha)
        for bad in ("main", "0"*40, "a"*39, "a"*40+";id"):
            with self.assertRaises(ValueError):
                deploy.checked_revision(bad)
        deploy.verify_main({"commit":{"sha":sha}}, sha)
        with self.assertRaises(ValueError):
            deploy.verify_main({"commit":{"sha":"b"*40}}, sha)
        run = {"head_sha":sha,"head_branch":"main","event":"push",
               "path":".github/workflows/ci.yml","status":"completed","conclusion":"success",
               "run_number":4,"run_attempt":1}
        deploy.verify_ci({"workflow_runs":[run]},sha)
        for altered in ({"head_sha":"b"*40},{"event":"pull_request"},
                        {"status":"in_progress"},{"conclusion":"failure"},
                        {"path":".github/workflows/other.yml"}):
            with self.assertRaises(ValueError):
                deploy.verify_ci({"workflow_runs":[{**run,**altered}]},sha)
        with self.assertRaises(ValueError):
            deploy.verify_ci({"workflow_runs":[run,{**run,"run_attempt":2,"conclusion":"failure"}]},sha)

    def test_exact_bank(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve()/"bank.sf2"
            data = b"test bank"
            path.write_bytes(data)
            pin={"id":"retro16-enhanced","status":"approved",
                 "bank_bytes":len(data),"bank_sha256":hashlib.sha256(data).hexdigest(),
                 "ci_run":1,"artifact_id":2}
            deploy.validate_pin(pin)
            deploy.verify_bank(path,pin)
            with self.assertRaises(ValueError):
                deploy.validate_pin({**pin,"status":"pending"})
            with self.assertRaises(ValueError):
                deploy.verify_bank(path,{**pin,"bank_sha256":"0"*64})
            link=path.parent/"link.sf2"
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                deploy.verify_bank(link,pin)

    def test_workflow_owner_and_main_only(self):
        workflow=(ROOT/".github/workflows/aeon-score-deploy.yml").read_text()
        for text in ("workflow_dispatch:", "github.actor == 'arthexis'",
                     "github.ref == 'refs/heads/main'", "[self-hosted, Linux, ARM64, gway-001]",
                     "timeout-minutes: 20", "persist-credentials: false",
                     "python3 -B scripts/deploy-aeon-score.py"):
            self.assertIn(text,workflow)
        self.assertNotIn("pull_request:",workflow)
        self.assertNotIn("secrets.",workflow)
