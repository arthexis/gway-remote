"""Offline tests for the standalone satellite bootstrap.

Use shared fixtures for stable protocol data and parameterization for invalid
inputs; subprocess and HTTP are always replaced in unit tests.
"""
import base64

import pytest

from gway_remote import wireguard_satellite as satellite


KEY = base64.b64encode(bytes(range(32))).decode()
OTHER = base64.b64encode(bytes(range(1, 33))).decode()
DEVICE = "gway-004"
TOKEN = "t" * 40
ENDPOINT = "register.gelectriic.com:51820"


@pytest.fixture
def enrollment():
    return {
        "device": DEVICE,
        "public_key": KEY,
        "address": "10.90.0.4/32",
        "server_endpoint": ENDPOINT,
        "server_public_key": OTHER,
        "server_tunnel_ip": "10.90.0.1",
    }


@pytest.fixture
def root(monkeypatch):
    monkeypatch.setattr(satellite.os, "geteuid", lambda: 0)


@pytest.fixture
def commands(monkeypatch):
    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        if args == ("wg", "genkey"):
            return "private"
        if args == ("wg", "pubkey"):
            return KEY
        return ""

    monkeypatch.setattr(satellite, "_run", run)
    return calls


@pytest.mark.parametrize("url", [
    "http://register.gelectriic.com/v1/enroll",
    "https://evil.test/v1/enroll",
    "https://register.gelectriic.com/v1/enroll?token=secret",
    "https://register.gelectriic.com:8443/v1/enroll",
    "https://user:pass@register.gelectriic.com/v1/enroll",
    "https://register.gelectriic.com/v1/enroll#secret",
])
def test_rejects_insecure_origin_without_network(url, monkeypatch):
    monkeypatch.setattr(satellite, "build_opener", lambda *args: pytest.fail("unexpected network access"))
    with pytest.raises(ValueError):
        satellite._enroll(url, DEVICE, KEY, TOKEN)


@pytest.mark.parametrize("change", [
    {"device": "gway-005"},
    {"public_key": OTHER},
    {"server_endpoint": "evil.test:51820"},
    {"address": "8.8.8.8/32"},
    {"address": "10.90.0.4/24"},
    {"server_public_key": KEY},
    {"server_tunnel_ip": "8.8.8.8"},
])
def test_rejects_mismatched_enrollment(enrollment, change):
    with pytest.raises(ValueError):
        satellite._validate({**enrollment, **change}, DEVICE, KEY, OTHER)


def test_accepts_matching_enrollment(enrollment):
    assert satellite._validate(enrollment, DEVICE, KEY, OTHER) == (
        "10.90.0.4/32", ENDPOINT, "10.90.0.1"
    )


def test_atomic_install_is_private_and_refuses_overwrite(tmp_path):
    config = tmp_path / "gway.conf"
    satellite._atomic_new(config, "first")
    assert config.read_text() == "first"
    assert config.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        satellite._atomic_new(config, "second")
    assert config.read_text() == "first"


def test_existing_config_never_reenrolls(tmp_path, monkeypatch, root, commands):
    config = tmp_path / "gway.conf"
    original = f"[Interface]\nPrivateKey = secret\n[Peer]\nPublicKey = {OTHER}\n"
    config.write_text(original)
    config.chmod(0o600)
    monkeypatch.setattr(satellite, "_enroll", lambda *args: pytest.fail("must not enroll"))

    result = satellite.bootstrap(DEVICE, OTHER, TOKEN, config=config)

    assert result == {"device": DEVICE, "configured": True, "reused": True}
    assert config.read_text() == original
    assert commands[-1][0] == ("systemctl", "enable", "--now", "wg-quick@gway.service")


def test_fresh_bootstrap_writes_config_and_activates(tmp_path, monkeypatch, root, commands, enrollment):
    config = tmp_path / "gway.conf"
    monkeypatch.setattr(satellite, "_enroll", lambda *args: enrollment)

    result = satellite.bootstrap(DEVICE, OTHER, TOKEN, config=config)

    assert result == {"device": DEVICE, "configured": True, "reused": False}
    assert "PrivateKey = private" in config.read_text()
    assert f"PublicKey = {OTHER}" in config.read_text()
    assert config.stat().st_mode & 0o777 == 0o600
    assert commands[-1][0] == ("systemctl", "enable", "--now", "wg-quick@gway.service")


def test_invalid_response_does_not_install_or_activate(tmp_path, monkeypatch, root, commands, enrollment):
    config = tmp_path / "gway.conf"
    monkeypatch.setattr(satellite, "_enroll", lambda *args: {**enrollment, "device": "gway-005"})

    with pytest.raises(ValueError, match="identity mismatch"):
        satellite.bootstrap(DEVICE, OTHER, TOKEN, config=config)

    assert not config.exists()
    assert not any(args[0] == "systemctl" for args, _ in commands)


def test_existing_unrelated_peer_is_preserved(tmp_path, monkeypatch, root, commands):
    config = tmp_path / "gway.conf"
    config.write_text(f"[Interface]\nPrivateKey = secret\n[Peer]\nPublicKey = {KEY}\n")
    config.chmod(0o600)
    monkeypatch.setattr(satellite, "_enroll", lambda *args: pytest.fail("must not enroll"))

    with pytest.raises(ValueError, match="existing tunnel differs"):
        satellite.bootstrap(DEVICE, OTHER, TOKEN, config=config)

    assert f"PublicKey = {KEY}" in config.read_text()
    assert not any(args[0] == "systemctl" for args, _ in commands)


def test_pending_key_survives_retry(tmp_path, monkeypatch, commands):
    config = tmp_path / "gway.conf"
    private, public, current = satellite._identity(config)
    assert (private, public, current) == ("private", KEY, None)
    assert (tmp_path / "gway.conf.pending-key").stat().st_mode & 0o777 == 0o600
    commands.clear()
    private2, public2, current2 = satellite._identity(config)
    assert (private2, public2, current2) == (private, public, None)
    assert not any(args == ("wg", "genkey") for args, _ in commands)
