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


def test_mount_preflight_rejects_mounted_root_or_second_partition(monkeypatch, tmp_path):
    from gway_remote import sd_inject
    import json
    boot = tmp_path / "bootfs"
    boot.mkdir()
    responses = {
        "findmnt": {"filesystems": [{
            "target": str(boot), "source": "/dev/sdz1",
            "fstype": "vfat", "options": "rw,relatime"}]},
        "part": {"blockdevices": [{
            "path": "/dev/sdz1", "type": "part", "rm": 1,
            "pkname": "sdz", "fstype": "vfat"}]},
        "disk": {"blockdevices": [{"type": "disk", "rm": 1}]},
        "layout": {"blockdevices": [{
            "name": "sdz", "mountpoints": [None],
            "children": [
                {"name": "sdz1", "mountpoints": [str(boot)]},
                {"name": "sdz2", "mountpoints": ["/"]}]}]},
    }
    def fake_command(*argv):
        if argv[0] == "findmnt":
            return json.dumps(responses["findmnt"])
        if argv[0] == "lsblk" and "-dnJ" in argv:
            return json.dumps(responses["disk"])
        if argv[0] == "lsblk" and "PATH,TYPE,RM,PKNAME,FSTYPE" in argv:
            return json.dumps(responses["part"])
        return json.dumps(responses["layout"])
    monkeypatch.setattr(sd_inject, "_command", fake_command)
    with pytest.raises(UnsafeCard, match="other mounted partitions"):
        sd_inject.inspect_bootfs(boot)
    responses["layout"]["blockdevices"][0]["children"].pop()
    assert sd_inject.inspect_bootfs(boot)["device"] == "/dev/sdz1"


def test_deferred_firstboot_renderer_is_valid_python_and_restricts_identity():
    from gway_remote.firstboot_deferred import firstboot_claim_source, firstboot_claim_unit
    source = firstboot_claim_source("gway-014", "arthe", "a" * 32)
    compile(source, "gway-sd-claim", "exec")
    assert "https://register.gelectriic.com" in source
    assert "ProxyHandler({})" in source
    assert "NoRedirect" in source
    assert "load_pem_private_key" in source
    assert "Restart=on-failure" in firstboot_claim_unit()
    with pytest.raises(ValueError):
        firstboot_claim_source("gway-0014", "arthe", "a" * 32)


def test_deferred_config_preserves_connect_and_existing_imager_data():
    yaml = pytest.importorskip("yaml")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PrivateFormat, NoEncryption,
    )
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(Encoding.PEM, PrivateFormat.PKCS8,
                                NoEncryption()).decode("ascii")
    raw = """#cloud-config
hostname: gway-014
users:
  - name: arthe
runcmd:
  - [echo, original]
packages:
  - curl
"""
    result = prepare_cloud_config(raw, node="gway-014", installer="arthe",
                                  preparation_id="a" * 32, private_key_pem=pem)
    parsed = yaml.safe_load(result)
    assert parsed["users"] == [{"name": "arthe"}]
    assert parsed["runcmd"][0] == ["echo", "original"]
    assert parsed["packages"] == ["curl", "python3-cryptography"]
    assert parsed["runcmd"][-1] == ["systemctl", "start", "--no-block",
                                   "gway-sd-claim.service"]
    assert parsed["runcmd"][1] == ["/usr/local/libexec/gway-connect-firstboot"]
    keys = [entry for entry in parsed["write_files"]
            if entry["path"] == "/etc/gway-remote/installation.key"]
    assert len(keys) == 1
    assert keys[0]["permissions"] == "0600"
    assert keys[0]["content"] == pem
    with pytest.raises(UnsafeCard, match="already injected"):
        prepare_cloud_config(result, node="gway-014", installer="arthe",
                             preparation_id="a" * 32, private_key_pem=pem)


def test_deferred_key_mismatch_and_invalid_pem_are_rejected():
    pytest.importorskip("yaml")
    raw = """#cloud-config
hostname: gway-014
"""
    with pytest.raises(UnsafeCard, match="supplied together"):
        prepare_cloud_config(raw, node="gway-014", installer="arthe",
                             preparation_id="a" * 32)
    with pytest.raises(UnsafeCard, match="invalid installation signing key"):
        prepare_cloud_config(raw, node="gway-014", installer="arthe",
                             preparation_id="a" * 32, private_key_pem="invalid")
