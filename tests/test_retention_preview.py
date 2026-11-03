"""Read-only retention preview contract for issue #306."""
import tempfile
import unittest
from pathlib import Path

from gway_remote.retention_preview import preview


class RetentionPreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.root = self.home / ".local/share/gway-agent-ops"
        self.releases = self.root / "releases"
        self.releases.mkdir(parents=True)
        self.active = self.releases / ("a" * 40)
        self.older = self.releases / ("b" * 40)
        for release in (self.active, self.older):
            (release / "bin").mkdir(parents=True)
            (release / "bin/agent").write_text("agent")
        self.entry = self.home / ".local/bin/agent"
        self.entry.parent.mkdir(parents=True)
        self.entry.symlink_to(self.active / "bin/agent")

    def inspect(self):
        return preview("gway-agent-ops", home=self.home)

    def test_direct_executable_link_protects_active_without_current(self):
        result = self.inspect()
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["deletion_enabled"])
        target = result["targets"][0]
        self.assertEqual(target["status"], "blocked")
        roles = {Path(row["path"]).name: row["classification"] for row in target["releases"]}
        self.assertEqual(roles[self.active.name], "referenced")
        self.assertEqual(roles[self.older.name], "unverified")
        self.assertTrue(all(row["deletable"] is False for row in target["releases"]))
        self.assertGreater(target["potential_bytes"], 0)

    def test_dry_run_is_pure_and_repeatable(self):
        before = {str(p): (p.lstat().st_mode, p.lstat().st_mtime_ns)
                  for p in self.home.rglob("*")}
        self.assertEqual(self.inspect(), self.inspect())
        after = {str(p): (p.lstat().st_mode, p.lstat().st_mtime_ns)
                 for p in self.home.rglob("*")}
        self.assertEqual(before, after)

    def test_symlink_release_is_never_traversed(self):
        outside = self.home / "outside"
        outside.mkdir()
        (outside / "private").write_text("do not inspect")
        (self.releases / ("c" * 40)).symlink_to(outside, target_is_directory=True)
        target = self.inspect()["targets"][0]
        self.assertTrue(any("symlink release" in error for error in target["errors"]))
        self.assertEqual(len(target["releases"]), 2)

    def test_activation_escape_blocks_inventory(self):
        outside = self.home / "outside"
        outside.mkdir()
        (self.root / "current").symlink_to(outside, target_is_directory=True)
        target = self.inspect()["targets"][0]
        self.assertTrue(any("escapes root" in error for error in target["errors"]))
        self.assertTrue(all(not item["deletable"] for item in target["releases"]))

    def test_missing_and_unsupported_roots(self):
        rows = preview(home=self.home)["targets"]
        self.assertEqual([row["name"] for row in rows],
                         ["ocpp-csms", "ocpp-reports", "ocpp-simulator",
                          "gway-lcd-sound", "gway-agent-ops", "gway-ap-kiosk",
                          "gway-rfid", "gway-bastion"])
        self.assertEqual(next(r for r in rows if r["name"] == "gway-ap-kiosk")["status"],
                         "unsupported")

    def test_unknown_target_rejected(self):
        with self.assertRaises(ValueError):
            preview("../bad", home=self.home)


if __name__ == "__main__":
    unittest.main()
