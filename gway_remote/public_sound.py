"""Pinned LCD Sound public-player promotion contract.

The root-owned helper is provisioned separately by an administrator. No generic
sudo, shell, path, or binary execution is authorized to the appliance runner.
"""
import hashlib
import os
from pathlib import Path
import re
import subprocess

HELPER = "/usr/local/sbin/gway-promote-sound"
PLAYER = Path("/usr/local/bin/sound")
SHA = re.compile(r"[0-9a-f]{40}\Z")


def promote(sha: str, *, release_root=None, execute=subprocess.run) -> str:
    if not SHA.fullmatch(sha):
        raise ValueError("Expected pinned full release SHA")
    root = Path(release_root or Path.home() / ".local/share/gway-lcd-sound")
    current = root / "current"
    expected = root / "releases" / sha[:12]
    if not current.is_symlink() or current.resolve(strict=True) != expected.resolve(strict=True):
        raise RuntimeError("Active LCD Sound release does not match pinned SHA")
    player = expected / "scripts/gway/sound.sh"
    if not player.is_file() or not os.access(player, os.X_OK):
        raise RuntimeError("Pinned public sound player is missing or not executable")
    if not Path(HELPER).is_file():
        raise RuntimeError("Privileged sound promotion helper is missing")
    expected_checksum = hashlib.sha256(player.read_bytes()).hexdigest()
    execute(["sudo", "-n", HELPER, f"promote:{sha}"], check=True, timeout=60)
    if hashlib.sha256(player.read_bytes()).hexdigest() != expected_checksum:
        raise RuntimeError("Pinned source changed during promotion")
    installed = PLAYER.read_bytes()
    if hashlib.sha256(installed).digest() != hashlib.sha256(player.read_bytes()).digest():
        raise RuntimeError("Public player checksum differs from pinned release")
    help_text = subprocess.run([str(PLAYER), "--help"], check=True, capture_output=True,
                               text=True, timeout=10).stdout
    if "--motif" not in help_text:
        raise RuntimeError("Public player does not expose --motif")
    return hashlib.sha256(installed).hexdigest()

