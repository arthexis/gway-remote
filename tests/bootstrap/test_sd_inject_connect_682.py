"""Hermetic contracts for SD injector and Raspberry Pi Connect first boot."""
from __future__ import annotations

import pytest

from gway_remote.firstboot_connect import connect_firstboot_script
from gway_remote.sd_inject import UnsafeCard, prepare_cloud_config


def test_connect_payload_preserves_auth_key_and_uses_user_manager():
    shell = connect_firstboot_script("arthe")
    assert "loginctl enable-linger" in shell
    assert "rpi-connect-signin.path" in shell
    assert 'systemctl --user --machine="$TARGET_USER@.host"' in shell
    assert "rpi-connect signin" not in shell
    assert "--auth-key" not in shell
    assert "auth.key" not in shell.split("# Image customisation")[1].split(
        "# Never print")[0]


@pytest.mark.parametrize("user", ["root", "", "../root", "a;echo", "A B"])
def test_invalid_installer_is_rejected(user):
    with pytest.raises(ValueError):
        connect_firstboot_script(user)


def test_cloud_config_preserves_imager_data_and_order():
    yaml = pytest.importorskip("yaml")
    raw = """#cloud-config
hostname: gway-014
users:
  - name: arthe
    shell: /bin/bash
ssh_pwauth: false
runcmd:
  - [echo, already-provisioned]
write_files:
  - path: /etc/motd
    content: existing
"""
    patched = prepare_cloud_config(raw, node="gway-014", installer="arthe")
    original = yaml.safe_load(raw)
    doc = yaml.safe_load(patched)
    assert doc["users"] == original["users"]
    assert doc["ssh_pwauth"] is False
    assert doc["runcmd"][0] == original["runcmd"][0]
    assert doc["write_files"][0] == original["write_files"][0]
    assert doc["runcmd"][-1] == ["/usr/local/libexec/gway-connect-firstboot"]
    assert "enable-linger" in doc["write_files"][-1]["content"]
    with pytest.raises(UnsafeCard, match="already injected"):
        prepare_cloud_config(patched, node="gway-014", installer="arthe")


def test_foreign_hostname_refused():
    pytest.importorskip("yaml")
    with pytest.raises(UnsafeCard, match="hostname"):
        prepare_cloud_config("#cloud-config\nhostname: gway-001\n",
                             node="gway-014", installer="arthe")


@pytest.mark.parametrize("raw", ["hello", "#cloud-config\n- one\n- two\n",
                                 "#cloud-config\nruncmd: not-a-list\n"])
def test_unsupported_cloud_config_is_rejected(raw):
    pytest.importorskip("yaml")
    with pytest.raises(UnsafeCard):
        prepare_cloud_config(raw, node="gway-014", installer="arthe")


def test_device_validation_does_not_write(monkeypatch, tmp_path):
    from gway_remote import sd_inject
    boot = tmp_path / "bootfs"
    boot.mkdir()
    (boot / "user-data").write_text("#cloud-config\nhostname: gway-014\n")
    monkeypatch.setattr(sd_inject, "inspect_bootfs",
                        lambda _: {"device": "/dev/sdz1"})
    pytest.importorskip("yaml")
    before = (boot / "user-data").read_bytes()
    receipt = sd_inject.inject(boot, node="gway-014", installer="arthe")
    assert receipt["written"] is False
    assert receipt["device"] == "/dev/sdz1"
    assert (boot / "user-data").read_bytes() == before


def test_injection_rejects_symlink_before_read(monkeypatch, tmp_path):
    from gway_remote import sd_inject
    boot = tmp_path / "bootfs"
    boot.mkdir()
    (boot / "user-data").symlink_to(tmp_path / "outside")
    monkeypatch.setattr(sd_inject, "inspect_bootfs",
                        lambda _: {"device": "/dev/sdz1"})
    with pytest.raises(UnsafeCard, match="unsafe"):
        sd_inject.inject(boot, node="gway-014", installer="arthe")
