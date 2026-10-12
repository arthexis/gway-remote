import unittest
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/firewall.sh"



class FirewallShortcutTests(unittest.TestCase):
    def test_firewall_shortcut_local_mode_and_override(self):
        text = SCRIPT.read_text()
        assert 'LOCAL_HOST=$(hostname -s)' in text
        assert 'MODE=local' in text
        assert 'MODE=remote' in text
        assert '-i "localhost," -c local --become' in text
        assert '-i "$HOST," -u "$USER" --become' in text
        assert 'gway_remote_apply_firewall=$APPLY' in text


    def test_firewall_shortcut_help(self):
        result = subprocess.run(["sh", str(SCRIPT), "--help"], capture_output=True, text=True)
        assert result.returncode == 0
        assert "--local" in result.stdout
        assert "--remote" in result.stdout
