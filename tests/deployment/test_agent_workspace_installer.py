"""Integration contract for opt-in Agent Ops workspace provisioning."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/configure-agent-seed-workspace.sh"


class WorkspaceInstallTests(unittest.TestCase):
    def test_local_seed_clone_and_idempotent_environment(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            seed = home / ".codex"
            seed.mkdir(mode=0o700)
            for name, value in (("config.toml", 'model = "test"\n'),
                                ("auth.json", '{"test":true}\n')):
                path = seed / name
                path.write_text(value)
                path.chmod(0o600)
            source = home / "Repos/gway-bastion"
            source.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            (source / "README.md").write_text("seed")
            subprocess.run(["git", "-C", str(source), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(source), "-c", "user.email=test@example.invalid",
                            "-c", "user.name=Test", "commit", "-qm", "seed"], check=True)
            (source / "uncommitted.txt").write_text("must not copy")
            config = home / ".config/gway-remote/mobile-api.env"
            config.parent.mkdir(parents=True)
            config.write_text("GWAY_REMOTE_API_TOKEN=unchanged\n")
            config.chmod(0o600)
            env = dict(os.environ, HOME=str(home))
            for key in ("GWAY_AGENT_WORKSPACE_ROOT", "GWAY_AGENT_SEED_CODEX_HOME",
                        "GWAY_AGENT_SEED_REPOSITORY"):
                env.pop(key, None)
            for _ in range(2):
                run = subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True,
                                     text=True, timeout=30)
                self.assertEqual(run.returncode, 0, run.stderr)
            runtime = home / ".local/share/gway-agent-ops"
            checkout = runtime / "workspaces/arthexis/gway-bastion"
            self.assertEqual(runtime.stat().st_mode & 0o777, 0o700)
            self.assertEqual(checkout.parent.stat().st_mode & 0o777, 0o700)
            self.assertTrue((checkout / ".git").is_dir())
            self.assertFalse((checkout / "uncommitted.txt").exists())
            lines = config.read_text().splitlines()
            self.assertEqual(lines.count("GWAY_REMOTE_API_TOKEN=unchanged"), 1)
            self.assertEqual(sum(x.startswith("GWAY_AGENT_WORKSPACE_ROOT=") for x in lines), 1)
            self.assertEqual(sum(x.startswith("GWAY_AGENT_SEED_CODEX_HOME=") for x in lines), 1)
            self.assertEqual((seed / "auth.json").read_text(), '{"test":true}\n')

    def test_invalid_seed_preserves_env(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            config = home / ".config/gway-remote/mobile-api.env"
            config.parent.mkdir(parents=True)
            config.write_text("GWAY_REMOTE_API_TOKEN=unchanged\n")
            config.chmod(0o600)
            run = subprocess.run(["sh", str(SCRIPT)], env={**os.environ, "HOME": str(home)},
                                 capture_output=True, text=True, timeout=10)
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(config.read_text(), "GWAY_REMOTE_API_TOKEN=unchanged\n")


if __name__ == "__main__":
    unittest.main()
