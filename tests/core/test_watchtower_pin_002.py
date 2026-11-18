"""Hermetic Watchtower gway-002 pin tests. No SSH, service, or real system paths."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from gway_remote import watchtower_pin_002 as pin


WIRE_KEY = (b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20"
            + b"K" * 32)
HOST_PUBLIC = "ssh-ed25519 " + base64.b64encode(WIRE_KEY).decode("ascii")
HOST_DIGEST = pin._digest(WIRE_KEY)
OLD_PUBLIC = "ssh-ed25519 " + base64.b64encode(
    b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + b"L" * 32
).decode("ascii")
OLD_DIGEST = pin._digest(base64.b64decode(OLD_PUBLIC.split()[1]))


def files(tmp_path):
    config = tmp_path / "execute.json"
    known = tmp_path / "known_hosts"
    identity = tmp_path / "relay_identity"
    host = tmp_path / "verified-gway-002-host.pub"
    uid = os.getuid()
    # The fixture's temporary user stands in for the privileged operator.
    raw_config = {
        "enabled": True,
        "nodes": [{
            "node": "gway-004", "address": "10.90.0.4",
            "ssh_host_alias": "gway-004", "known_hosts": str(known),
            "identity_file": str(identity), "host_key_sha256": OLD_DIGEST,
            "remote_user": "gway-relay",
        }],
    }
    config.write_text(json.dumps(raw_config))
    known.write_text("gway-004 " + OLD_PUBLIC + "\n")
    identity.write_bytes(b"private fixture, never printed")
    host.write_text(HOST_PUBLIC + "\n")
    for path in (config, known, identity, host):
        path.chmod(0o600)
    return config, known, identity, host, uid


def _fake_trust(monkeypatch):
    """Substitute only the sandbox owner for root; preserve actual file checks."""
    original_file = pin._file
    original_dir = pin._directory
    monkeypatch.setattr(pin, "_file", lambda path, *, uid, maximum, private=False:
                        original_file(path, uid=os.getuid(), maximum=maximum,
                                      private=private))
    monkeypatch.setattr(pin, "_directory", lambda path, *, owner=None:
                        original_dir(path, owner=os.getuid() if owner == 0 else owner))
    monkeypatch.setattr(pin.os, "geteuid", lambda: 0)


def fake_ledger():
    now = datetime.now(timezone.utc)
    return {"nodes": [{
        "node": pin.NODE, "state": "active", "address": "10.90.0.2/32",
        "host_identity": {
            "schema": 1, "node": pin.NODE, "state": "active",
            "rotation_state": "stable",
            "wireguard_identity": base64.b64encode(b"W" * 32).decode("ascii"),
            "host_public_key": HOST_PUBLIC,
            "enrollment_binding": "c" * 64,
            "created_at": (now - timedelta(days=1)).isoformat(),
            "valid_until": (now + timedelta(days=1)).isoformat(),
        },
    }]}


def fake_inventory():
    return {"nodes": [{
        "node": pin.NODE, "registered": True, "identity_verified": True,
        "execute_eligible": True, "reachable": "reachable",
        "address": "10.90.0.2",
    }]}



class TestWatchtowerPin002:
    def test_read_only_plan_requires_matching_authoritative_host_key(self, tmp_path, monkeypatch):
        config, known, identity, host, uid = files(tmp_path)
        _fake_trust(monkeypatch)
        monkeypatch.setattr(pin, "LEDGER", tmp_path / "does-not-exist")
        monkeypatch.setattr(pin, "snapshot_from_path", lambda _: fake_ledger())
        monkeypatch.setattr(pin.node_registry_inventory, "load", lambda _: fake_inventory())
        plan = pin.plan(service_uid=uid, config=config, host_key=host,
                        inventory=tmp_path / "inventory")
        assert plan["pin_digest"] == HOST_DIGEST
        assert plan["existing_nodes"] == ("gway-004",)
        assert b"gway-004" in plan["known"][2] and b"gway-002" in plan["known"][2]
        assert plan["known"][1] == known.read_bytes()  # preview never writes
        assert plan["config"][1] == config.read_bytes()
        assert plan["config"][2].count(b"gway-002") == 2
        host.write_text(OLD_PUBLIC + "\n")
        with pytest.raises(ValueError, match="differs"):
            pin.plan(service_uid=uid, config=config, host_key=host,
                     inventory=tmp_path / "inventory")
    
    
    def test_plan_refuses_stale_grant_existing_alias_and_mismatched_pin(self, tmp_path, monkeypatch):
        config, known, identity, host, uid = files(tmp_path)
        _fake_trust(monkeypatch)
        monkeypatch.setattr(pin, "snapshot_from_path", lambda _: fake_ledger())
        denied = fake_inventory()
        denied["nodes"][0]["execute_eligible"] = False
        monkeypatch.setattr(pin.node_registry_inventory, "load", lambda _: denied)
        with pytest.raises(ValueError, match="eligibility"):
            pin.plan(service_uid=uid, config=config, host_key=host)
        monkeypatch.setattr(pin.node_registry_inventory, "load", lambda _: fake_inventory())
        known.write_text(known.read_text() + "gway-002 " + HOST_PUBLIC + "\n")
        with pytest.raises(ValueError, match="existing gway-002"):
            pin.plan(service_uid=uid, config=config, host_key=host)
        known.write_text("gway-004 " + HOST_PUBLIC + "\n")
        with pytest.raises(ValueError, match="pin is no longer valid"):
            pin.plan(service_uid=uid, config=config, host_key=host)
    
    
    def journal_fixture(self, tmp_path, monkeypatch):
        config, known, _, _, uid = files(tmp_path)
        _fake_trust(monkeypatch)
        monkeypatch.setattr(pin, "CONFIG", config)
        before_config, before_known = config.read_bytes(), known.read_bytes()
        after_config = before_config + b"\n"
        after_known = before_known + b"gway-002 " + HOST_PUBLIC.encode() + b"\n"
        p = {"config": (config, before_config, after_config, config.stat()),
             "known": (known, before_known, after_known, known.stat())}
        monkeypatch.setattr(pin, "plan", lambda *, service_uid: p)
        root = tmp_path / "journal-state"
        return root, config, known, before_config, before_known, uid
    
    
    def test_explicit_apply_keeps_durable_images_and_manual_recovery(self, tmp_path, monkeypatch):
        root, config, known, before_config, before_known, uid = self.journal_fixture(
            tmp_path, monkeypatch)
        with pytest.raises(pin.PinRefused, match="explicit relay"):
            pin.apply(service_uid=uid, approval="", relay_confirmed=True, state=root)
        assert not root.exists()
        assert pin.apply(service_uid=uid, approval=pin._APPROVAL,
                         relay_confirmed=True, state=root) == "pending_acceptance"
        assert config.read_bytes() != before_config
        assert known.read_bytes() != before_known
        assert (root / "config.before").read_bytes() == before_config
        assert (root / "known.before").read_bytes() == before_known
        assert json.loads((root / "journal.json").read_text())["state"] == "pending_acceptance"
        with pytest.raises(FileExistsError):
            pin.apply(service_uid=uid, approval=pin._APPROVAL,
                      relay_confirmed=True, state=root)
        assert pin.recover(state=root, approval="I_ACCEPT_GWAY_002_PIN_ROLLBACK") == "rolled_back"
        assert config.read_bytes() == before_config
        assert known.read_bytes() == before_known
        assert pin.recover(state=root, approval="I_ACCEPT_GWAY_002_PIN_ROLLBACK") == "already_rolled_back"
    
    
    def test_failure_between_file_swaps_rolls_back_without_replaying(self, tmp_path, monkeypatch):
        root, config, known, before_config, before_known, uid = self.journal_fixture(
            tmp_path, monkeypatch)
        original_replace = pin._atomic_file
        calls = []
    
        def one_failure(path, raw, info):
            calls.append(path.name)
            if len(calls) == 2:
                raise OSError("simulated crash before second swap")
            return original_replace(path, raw, info)
    
        monkeypatch.setattr(pin, "_atomic_file", one_failure)
        with pytest.raises(OSError, match="simulated crash"):
            pin.apply(service_uid=uid, approval=pin._APPROVAL,
                      relay_confirmed=True, state=root)
        assert config.read_bytes() == before_config
        assert known.read_bytes() == before_known
        assert json.loads((root / "journal.json").read_text())["state"] == "rolled_back"
    
    
    def test_recovery_does_not_overwrite_unknown_concurrent_bytes(self, tmp_path, monkeypatch):
        root, config, known, before_config, before_known, uid = self.journal_fixture(
            tmp_path, monkeypatch)
        pin.apply(service_uid=uid, approval=pin._APPROVAL,
                  relay_confirmed=True, state=root)
        config.write_bytes(b'{"unrelated":"operator changes"}')
        config.chmod(0o600)
        with pytest.raises(pin.PinRefused, match="concurrent"):
            pin.recover(state=root, approval="I_ACCEPT_GWAY_002_PIN_ROLLBACK")
        assert config.read_bytes() == b'{"unrelated":"operator changes"}'
        assert json.loads((root / "journal.json").read_text())["state"] == "pending_acceptance"
    