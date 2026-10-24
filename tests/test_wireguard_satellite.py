"""Offline acceptance tests for the standalone satellite bootstrap."""
import base64
from pathlib import Path
import pytest
from gway_remote import wireguard_satellite as satellite

KEY = base64.b64encode(bytes(range(32))).decode()
OTHER = base64.b64encode(bytes(range(1, 33))).decode()


def test_rejects_insecure_origin_without_network():
    with pytest.raises(ValueError):
        satellite._enroll("http://register.gelectriic.com/v1/enroll", "gway-004", KEY, "t" * 40)
    with pytest.raises(ValueError):
        satellite._enroll("https://evil.test/v1/enroll", "gway-004", KEY, "t" * 40)
    with pytest.raises(ValueError):
        satellite._enroll("https://register.gelectriic.com/v1/enroll?token=secret", "gway-004", KEY, "t" * 40)


def test_response_must_match_identity_and_endpoint():
    data = {"device": "gway-004", "public_key": KEY, "address": "10.90.0.4/32",
            "server_endpoint": "register.gelectriic.com:51820"}
    assert satellite._validate(data, "gway-004", KEY, OTHER)[0] == "10.90.0.4/32"
    with pytest.raises(ValueError):
        satellite._validate({**data, "public_key": OTHER}, "gway-004", KEY, OTHER)
    with pytest.raises(ValueError):
        satellite._validate({**data, "server_endpoint": "evil.test:51820"}, "gway-004", KEY, OTHER)


def test_atomic_install_is_private_and_refuses_overwrite(tmp_path):
    config = tmp_path / "gway.conf"
    satellite._atomic_new(config, "first")
    assert config.read_text() == "first"
    assert config.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        satellite._atomic_new(config, "second")
    assert config.read_text() == "first"


def test_existing_config_never_reenrolls(tmp_path, monkeypatch):
    config = tmp_path / "gway.conf"
    config.write_text(f"[Interface]\nPrivateKey = secret\n[Peer]\nPublicKey = {OTHER}\n")
    config.chmod(0o600)
    calls = []
    monkeypatch.setattr(satellite.os, "geteuid", lambda: 0)
    monkeypatch.setattr(satellite, "_run", lambda *args, **kwargs: calls.append(args) or KEY)
    monkeypatch.setattr(satellite, "_enroll", lambda *args: pytest.fail("must not enroll"))
    result = satellite.bootstrap("gway-004", OTHER, "t" * 40, config=config)
    assert result["reused"]
    assert calls[-1] == ("systemctl", "enable", "--now", "wg-quick@gway.service")


def test_fresh_bootstrap_writes_config_and_activates(tmp_path, monkeypatch):
    config = tmp_path / "gway.conf"
    monkeypatch.setattr(satellite.os, "geteuid", lambda: 0)
    calls = []
    def run(*args, **kwargs):
        calls.append(args)
        return "private" if args[1] == "genkey" else KEY
    monkeypatch.setattr(satellite, "_run", run)
    monkeypatch.setattr(satellite, "_enroll", lambda *args: {
        "device": "gway-004", "public_key": KEY, "address": "10.90.0.4/32",
        "server_endpoint": "register.gelectriic.com:51820"})
    result = satellite.bootstrap("gway-004", OTHER, "t" * 40, config=config)
    assert result["configured"] and not result["reused"]
    assert "PrivateKey = private" in config.read_text()
    assert calls[-1][0] == "systemctl"
