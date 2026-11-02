"""Pinned standalone MCP runtime packaging, without root or service actions."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("mcp_stage", ROOT / "scripts/stage-mcp-runtime.py")
STAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAGE)


class MCPRuntimeStageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.prefix = self.root / "installed"
        subprocess.run(["git", "init", "-q", str(self.source)], check=True)
        package = self.source / "gway_remote"
        package.mkdir()
        (package / "__init__.py").write_text("")
        for module in ("mcp_http", "mcp_bearer_gateway", "mcp_link_http"):
            (package / (module + ".py")).write_text("print('pinned-runtime')\n")
        units = self.source / "deploy/mcp-bearer"
        units.mkdir(parents=True)
        (units / "test.service").write_text("[Service]\n")
        subprocess.run(["git", "-C", str(self.source), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.source), "-c", "user.name=Test", "-c",
                        "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)
        self.sha = subprocess.check_output(["git", "-C", str(self.source), "rev-parse", "HEAD"], text=True).strip()

    def test_stages_exact_committed_package_and_importable_launcher(self):
        (self.source / "gway_remote/mcp_http.py").write_text("raise RuntimeError('dirty')\n")
        (self.source / "gway_remote/untracked.py").write_text("secret = True\n")
        release = STAGE.stage(self.source, self.sha, self.prefix)
        self.assertFalse((release / "gway_remote/untracked.py").exists())
        output = subprocess.check_output(["/usr/bin/python3", "-I", str(self.prefix / "current/run.py"), "mcp_http"], text=True)
        self.assertEqual(output.strip(), "pinned-runtime")
        manifest = json.loads((release / "manifest.json").read_text())
        self.assertEqual(manifest["revision"], self.sha)
        self.assertIn("gway_remote/mcp_http.py", manifest["sha256"])
        self.assertEqual(release.stat().st_mode & 0o777, 0o755)
        self.assertEqual((release / "gway_remote").stat().st_mode & 0o777, 0o755)
        self.assertFalse((self.prefix / "previous").exists())

    def test_repeated_stage_preserves_release_and_rejects_tampering(self):
        release = STAGE.stage(self.source, self.sha, self.prefix)
        STAGE.stage(self.source, self.sha, self.prefix)
        self.assertFalse((self.prefix / "previous").exists())
        (release / "gway_remote/mcp_http.py").write_text("tampered\n")
        with self.assertRaisesRegex(ValueError, "immutable release differs"):
            STAGE.stage(self.source, self.sha, self.prefix)
        self.assertEqual((self.prefix / "current").resolve(), release)

    def test_rejects_writable_existing_code_without_switching_release(self):
        release = STAGE.stage(self.source, self.sha, self.prefix)
        (release / "gway_remote/mcp_http.py").chmod(0o666)
        with self.assertRaisesRegex(ValueError, "immutable release differs"):
            STAGE.stage(self.source, self.sha, self.prefix)
        self.assertEqual((self.prefix / "current").resolve(), release)

    def test_rejects_unsafe_existing_root_without_changing_permissions(self):
        self.prefix.mkdir(mode=0o755)
        self.prefix.chmod(0o777)
        with self.assertRaisesRegex(ValueError, "not group/world writable"):
            STAGE.stage(self.source, self.sha, self.prefix)
        self.assertEqual(self.prefix.stat().st_mode & 0o777, 0o777)
        self.assertFalse((self.prefix / "current").exists())

    def test_rejects_root_owned_by_another_identity(self):
        self.prefix.mkdir(mode=0o755)
        with patch.object(STAGE.os, "geteuid", return_value=os.geteuid() + 1):
            with self.assertRaisesRegex(ValueError, "owned by the installer"):
                STAGE.stage(self.source, self.sha, self.prefix)
        self.assertFalse((self.prefix / "releases").exists())

    def test_rejects_symlink_ancestor_without_writing_target(self):
        real = self.root / "real"
        real.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "ancestors must not be symlinks"):
            STAGE.stage(self.source, self.sha, alias / "mcp")
        self.assertFalse((real / "mcp").exists())

    def test_requires_exact_commit_before_creating_destination(self):
        for revision in ("main", "HEAD", self.sha[:12], "--help"):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                STAGE.stage(self.source, revision, self.prefix)
        self.assertFalse(self.prefix.exists())

    def test_second_release_retains_previous_for_rollback(self):
        first = STAGE.stage(self.source, self.sha, self.prefix)
        (self.source / "gway_remote/mcp_http.py").write_text("print('second')\n")
        subprocess.run(["git", "-C", str(self.source), "-c", "user.name=Test", "-c",
                        "user.email=test@example.invalid", "commit", "-qam", "second"], check=True)
        second_sha = subprocess.check_output(["git", "-C", str(self.source), "rev-parse", "HEAD"], text=True).strip()
        second = STAGE.stage(self.source, second_sha, self.prefix)
        self.assertEqual((self.prefix / "current").resolve(), second)
        self.assertEqual((self.prefix / "previous").resolve(), first)
        STAGE.stage(self.source, second_sha, self.prefix)
        self.assertEqual((self.prefix / "previous").resolve(), first)
