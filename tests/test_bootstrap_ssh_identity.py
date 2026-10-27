"""Bootstrap cannot overwrite pre-existing SSH identities."""
import base64
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from gway_remote.wireguard_satellite import _ssh_host_public_key

WIRE = bytes((0,0,0,11)) + b"ssh-ed25519" + bytes((0,0,0,32))
PUB = "ssh-ed25519 " + base64.b64encode(WIRE + bytes(range(32))).decode()


def test_existing_identity_is_preserved(tmp_path):
    public = tmp_path / "ssh_host_ed25519_key.pub"
    private = tmp_path / "ssh_host_ed25519_key"
    public.write_text(PUB)
    private.write_text("fake-private-material")
    os.chmod(private, 0o600)
    with patch("gway_remote.wireguard_satellite.subprocess.run") as run:
        assert _ssh_host_public_key(public) == PUB
        run.assert_not_called()


def test_incomplete_or_symlinked_identity_fails_closed(tmp_path):
    public = tmp_path / "ssh_host_ed25519_key.pub"
    private = tmp_path / "ssh_host_ed25519_key"
    private.write_text("exists")
    os.chmod(private, 0o600)
    with pytest.raises(ValueError, match="incomplete"):
        _ssh_host_public_key(public)
    private.unlink()
    public.symlink_to(tmp_path / "missing")
    with pytest.raises(ValueError, match="unsafe"):
        _ssh_host_public_key(public)
