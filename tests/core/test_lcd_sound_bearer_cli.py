"""Hermetic operator CLI source-only issuance and revocation."""
from pathlib import Path
import subprocess
import sys
import unittest

from gway_remote.mcp_bearer import BearerVerifier


class LCDSoundBearerCLITests(unittest.TestCase):
    def test_lcd_source_token_issued_separately_and_revoked(self):
        from tempfile import TemporaryDirectory
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        db = Path(temp.name) / "credentials.sqlite3"
        cli = Path(__file__).resolve().parents[2] / "scripts/mcp-bearer.py"
        issued = subprocess.run(
            [sys.executable, str(cli), "--database", str(db), "issue",
             "--days", "1", "--scope", "gway:lcd-sound"],
            capture_output=True, text=True, timeout=10, check=True)
        token = issued.stdout.strip()
        assert token.startswith("gwr_")
        verifier = BearerVerifier(db)
        principal = verifier.lcd_sound_principal(token)
        assert len(principal) == 24
        assert not verifier.verify(token, required_scope="gway:read")
        assert not verifier.verify(token, required_scope="gway:execute")

        subprocess.run(
            [sys.executable, str(cli), "--database", str(db), "revoke", principal],
            capture_output=True, text=True, timeout=10, check=True)
        assert not verifier.verify(token, required_scope="gway:lcd-sound")
