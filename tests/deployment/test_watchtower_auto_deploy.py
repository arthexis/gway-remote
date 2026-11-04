"""D1: automatic Watchtower deployment must use the existing locked Ansible path."""
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/deploy-backend.yml"
SCRIPT = ROOT / "scripts/watchtower-auto-deploy.sh"
PLAYBOOK = ROOT / "ansible/playbooks/watchtower-mcp.yml"


class WatchtowerAutoDeployTests(unittest.TestCase):
    def test_only_main_push_and_existing_runner(self):
        workflow = WORKFLOW.read_text()
        self.assertIn("on:\n  push:\n    branches: [main]", workflow)
        self.assertIn("watchtower:\n    name: Deploy Watchtower MCP", workflow)
        job = workflow.split("\n  watchtower:\n", 1)[1]
        self.assertIn("needs: deploy", job)
        self.assertIn("always()", job)
        self.assertIn("runs-on: [self-hosted, Linux, ARM64, gway-001]", job)
        self.assertIn("github.ref == 'refs/heads/main'", job)
        self.assertIn("github.sha", job)
        self.assertIn("CURRENT_SHA", job)
        self.assertIn("actions/checkout@v4", job)
        self.assertIn("persist-credentials: false", job)
        self.assertNotIn("workflow_dispatch:", job)
        self.assertNotIn("secrets.", job)
        self.assertNotIn("sudo ", job)

    def test_hard_pinned_known_host_and_fixed_reviewed_script(self):
        job = WORKFLOW.read_text().split("\n  watchtower:\n", 1)[1]
        self.assertIn("BatchMode=yes", job)
        self.assertIn("StrictHostKeyChecking=yes", job)
        self.assertIn("gelectriic.com", job)
        self.assertIn("scripts/watchtower-auto-deploy.sh", job)
        self.assertIn('"sh -s -- $TARGET_SHA"', job)
        self.assertNotIn("StrictHostKeyChecking=no", job)
        self.assertNotIn("UserKnownHostsFile=/dev/null", job)

    def test_remote_executes_only_fixed_existing_ansible(self):
        script = SCRIPT.read_text()
        self.assertEqual(subprocess.run(["sh", "-n", str(SCRIPT)], capture_output=True).returncode, 0)
        self.assertIn('[ "$(id -un)" = ubuntu ]', script)
        self.assertIn("sudo -n true", script)
        self.assertIn("flock -n 9", script)
        self.assertIn('state="$HOME/.local/state/gway-remote"', script)
        self.assertIn("git clone --quiet --depth 1 --single-branch --branch main", script)
        self.assertIn('observed=$(git -C "$tmp/source" rev-parse --verify HEAD)', script)
        self.assertIn('[ "$observed" = "$sha" ]', script)
        self.assertIn('"$tmp/source/ansible/playbooks/watchtower-mcp.yml"', script)
        self.assertIn('actual=$(readlink /opt/gway-mcp/current)', script)
        self.assertIn('[ "$actual" = "releases/$sha" ]', script)
        self.assertIn("gway-mcp-link.service", script)
        self.assertIn("gway-mcp-gateway.service", script)
        for forbidden in ("git reset --hard", "ssh-keyscan", "sudo chmod", "systemctl enable",
                          "systemctl restart", "nginx", "curl | sh",
                          "gway-remote-deploy.service", "authorized_keys"):
            self.assertNotIn(forbidden, script)
        self.assertIn("rescue:", PLAYBOOK.read_text())

    def test_invalid_revisions_fail_without_probing_watchtower(self):
        for args in ([], ["abc"], ["g" * 40], ["a" * 39], ["a" * 41], ["a" * 40, "extra"]):
            with self.subTest(args=args):
                proc = subprocess.run(["sh", str(SCRIPT), *args],
                                      text=True, capture_output=True, timeout=3)
                self.assertEqual(proc.returncode, 2, proc.stderr)


if __name__ == "__main__":
    unittest.main()
