"""Bootstrap served as client.py must work outside the gway_remote package."""
import base64
import subprocess
import sys
from pathlib import Path

from gway_remote.host_identity import validate_public_key

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "gway_remote/wireguard_satellite.py"
WIRE = bytes((0, 0, 0, 11)) + b"ssh-ed25519" + bytes((0, 0, 0, 32)) + bytes(range(32))
KEY = "ssh-ed25519 " + base64.b64encode(WIRE).decode()


def test_bootstrap_client_can_validate_identity_outside_package(tmp_path):
    script = tmp_path / "client.py"
    script.write_bytes(CLIENT.read_bytes())
    private = tmp_path / "ssh_host_ed25519_key"
    public = tmp_path / "ssh_host_ed25519_key.pub"
    private.write_text("placeholder")
    private.chmod(0o600)
    public.write_text(KEY + "\n")
    code = (
        "import importlib.util, sys; "
        "spec=importlib.util.spec_from_file_location('client',sys.argv[1]); "
        "module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); "
        "print(module._ssh_host_public_key(__import__('pathlib').Path(sys.argv[2])))"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code, str(script), str(public)],
                            text=True, capture_output=True, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == validate_public_key(KEY)


def test_standalone_validator_rejects_invalid_keys():
    from gway_remote.wireguard_satellite import _validate_ssh_host_public_key
    import pytest
    for key in ("ssh-rsa AAAA", KEY + " comment", "ssh-ed25519 !!!",
                "ssh-ed25519 " + base64.b64encode(b"invalid").decode()):
        with pytest.raises(ValueError):
            _validate_ssh_host_public_key(key)
