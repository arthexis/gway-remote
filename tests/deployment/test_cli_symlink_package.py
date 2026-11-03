"""Regression: zipapp packaging must dereference the archive release link."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
import zipfile


class CliPackageSymlinkTests(unittest.TestCase):
    def test_zipapp_source_copy_dereferences_relative_package_symlink(self):
        source = Path("scripts/install-cli.sh").read_text()
        self.assertIn('cp -R "$ROOT/gway_remote/." "$TMP/gway_remote/"', source)
        self.assertNotIn('cp -R "$ROOT/gway_remote" "$TMP/gway_remote"', source)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "opt"
            pkg = root / ".package-releases" / "abc123" / "gway_remote"
            pkg.mkdir(parents=True)
            (pkg / "__init__.py").write_text("")
            (pkg / "__main__.py").write_text("def main(): pass\n")
            (root / "gway_remote").symlink_to(".package-releases/abc123/gway_remote")
            staging = Path(temp) / "stage"
            staging.mkdir()
            subprocess.run(["sh", "-ec", """
                mkdir -m 755 "$TMP/gway_remote"
                cp -R "$ROOT/gway_remote/." "$TMP/gway_remote/"
                printf 'from gway_remote.__main__ import main\\nmain()\\n' > "$TMP/__main__.py"
                python3 -m zipapp "$TMP" -p '/usr/bin/env python3' -o "$ROOT/out.pyz"
            """], env={**os.environ, "ROOT": str(root), "TMP": str(staging)},
                           check=True, capture_output=True, text=True)
            with zipfile.ZipFile(root / "out.pyz") as z:
                self.assertIn("gway_remote/__main__.py", z.namelist())
                self.assertIn("gway_remote/__init__.py", z.namelist())
                self.assertFalse(z.getinfo("gway_remote/").external_attr >> 16 & 0o170000 == 0o120000)


if __name__ == "__main__":
    unittest.main()
