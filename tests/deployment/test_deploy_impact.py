"""Hermetic push-impact policy and workflow admission wiring."""
import pathlib
import subprocess
import tempfile
import unittest

from gway_remote.deploy_impact import SAFE_PATHS, classify_paths, classify_push

ROOT = pathlib.Path(__file__).resolve().parents[2]


class PushImpactTests(unittest.TestCase):
    def test_exact_v1_paths_only(self):
        self.assertEqual(classify_paths(sorted(SAFE_PATHS)), "skip")
        for path in SAFE_PATHS:
            self.assertEqual(classify_paths([path]), "skip")
        for path in (".github/workflows/deploy-backend.yml", "deploy.sh",
                     "gway_remote/mcp_http.py", "docs/operator-commands.md",
                     "scripts/watchtower-auto-deploy.sh",
                     "gway_remote/development_evidence.py/extra"):
            self.assertEqual(classify_paths([*SAFE_PATHS, path]), "deploy")

    def test_missing_or_malformed_evidence_fails_closed(self):
        for paths in ([], (), ["", "docs/development-evidence-v1.md"],
                      ["/docs/development-evidence-v1.md"], ["bad\x00name"]):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                classify_paths(paths)
        for before, after in (("0" * 40, "a" * 40),
                              ("a" * 40, "a" * 40),
                              ("main", "b" * 40)):
            with self.assertRaises(ValueError):
                classify_push(before, after)

    def test_full_git_range_rename_and_operational_change(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            def git(*args):
                return subprocess.run(["git", "-C", d, *args], capture_output=True,
                                      check=True, text=True).stdout.strip()
            def put(name, content):
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
            git("init", "-q")
            git("config", "user.email", "test@example.invalid")
            git("config", "user.name", "Hermetic test")
            put("README.md", "baseline")
            git("add", ".")
            git("commit", "-qm", "base")
            base = git("rev-parse", "HEAD")
            put("docs/development-evidence-v1.md", "v1")
            git("add", ".")
            git("commit", "-qm", "offline")
            offline = git("rev-parse", "HEAD")
            def runner(argv, **kwargs):
                return subprocess.run(["git", "-C", d, *argv[1:]], **kwargs)
            self.assertEqual(classify_push(base, offline, runner=runner), "skip")
            put("deploy.sh", "changed")
            git("add", ".")
            git("commit", "-qm", "runtime")
            runtime = git("rev-parse", "HEAD")
            self.assertEqual(classify_push(base, runtime, runner=runner), "deploy")
            with self.assertRaises(subprocess.CalledProcessError):
                classify_push(runtime, base, runner=runner)
            git("mv", "docs/development-evidence-v1.md", "docs/renamed.md")
            git("commit", "-qm", "rename")
            renamed = git("rev-parse", "HEAD")
            self.assertEqual(classify_push(runtime, renamed, runner=runner), "deploy")

    def test_admission_runs_before_any_self_hosted_job(self):
        workflow = (ROOT / ".github/workflows/deploy-backend.yml").read_text()
        self.assertIn("runs-on: ubuntu-latest", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("python3 -m gway_remote.deploy_impact", workflow)
        self.assertIn("needs: admission", workflow)
        self.assertIn("needs: [admission, deploy]", workflow)
        self.assertEqual(workflow.count("needs.admission.outputs.deploy == 'true'"), 2)
        self.assertIn("needs.admission.result == 'success'", workflow)
        self.assertIn("github.event.before", workflow)
        self.assertIn("github.sha", workflow)
        # The guard must not classify changes to itself as safe.
        self.assertNotIn(".github/workflows/deploy-backend.yml", SAFE_PATHS)


if __name__ == "__main__":
    unittest.main()
