"""Hermetic operator CLI source-only issuance and revocation."""
from pathlib import Path
import subprocess
import os
import sys
import unittest

from gway_remote.mcp_bearer import BearerVerifier


class LCDSoundBearerCLITests(unittest.TestCase):
    def test_lcd_source_token_issued_separately_and_revoked(self):
        from tempfile import TemporaryDirectory
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        db = Path(temp.name) / "credentials.sqlite3"
        root = Path(__file__).resolve().parents[2]
        cli = root / "scripts/mcp-bearer.py"
        env = dict(os.environ)
        env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
        issued = subprocess.run(
            [sys.executable, str(cli), "--database", str(db), "issue",
             "--days", "1", "--scope", "gway:lcd-sound"],
            capture_output=True, text=True, timeout=10, check=True, env=env)
        token = issued.stdout.strip()
        assert token.startswith("gwr_")
        verifier = BearerVerifier(db)
        principal = verifier.lcd_sound_principal(token)
        assert len(principal) == 24
        assert not verifier.verify(token, required_scope="gway:read")
        assert not verifier.verify(token, required_scope="gway:execute")

        subprocess.run(
            [sys.executable, str(cli), "--database", str(db), "revoke", principal],
            capture_output=True, text=True, timeout=10, check=True, env=env)
        assert not verifier.verify(token, required_scope="gway:lcd-sound")
