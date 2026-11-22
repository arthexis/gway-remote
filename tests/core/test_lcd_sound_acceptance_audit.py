import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/lcd-sound-acceptance-audit.py"
spec = importlib.util.spec_from_file_location("lcd_sound_acceptance_audit", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class LocalCommandInventoryTest(unittest.TestCase):
    def test_finds_user_install_when_path_omits_it(self):
        with tempfile.TemporaryDirectory() as home:
            binary = Path(home) / ".local/bin/gway-lcd-sound"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\nexit 0\n")
            binary.chmod(0o755)
            with patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
                self.assertIsNone(audit.shutil.which("gway-lcd-sound"))
                self.assertEqual(audit.local_commands(home)["gway-lcd-sound"], str(binary))
                binary.chmod(0o644)
                self.assertIsNone(audit.local_commands(home)["gway-lcd-sound"])


if __name__ == "__main__":
    unittest.main()
