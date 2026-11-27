"""Unittest-discoverable, hermetic Watchtower pin contract and recovery tests."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from gway_remote import watchtower_pin_002 as pin


WIRE_KEY = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + b"K" * 32
HOST_PUBLIC = "ssh-ed25519 " + base64.b64encode(WIRE_KEY).decode("ascii")
HOST_DIGEST = pin._digest(WIRE_KEY)
OLD_KEY = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + b"L" * 32
OLD_PUBLIC = "ssh-ed25519 " + base64.b64encode(OLD_KEY).decode("ascii")
OLD_DIGEST = pin._digest(OLD_KEY)


def fake_ledger():
    now = datetime.now(timezone.utc)
    return {"nodes": [{
        "node": pin.NODE, "state": "active", "address": "10.90.0.2/32",
        "host_identity": {
            "schema": 1, "node": pin.NODE, "state": "active",
            "rotation_state": "stable",
            "wireguard_identity": base64.b64encode(b"W" * 32).decode("ascii"),
            "host_public_key": HOST_PUBLIC, "enrollment_binding": "c" * 64,
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


class WatchtowerPin002Tests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="watchtower-pin-002-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.uid = os.getuid()
        self.config = self.root / "execute.json"
        self.known = self.root / "known_hosts"
        self.identity = self.root / "relay_identity"
        self.host = self.root / "verified-gway-002-host.pub"
        self.config.write_text(json.dumps({
            "enabled": True, "nodes": [{
                "node": "gway-004", "address": "10.90.0.4",
                "ssh_host_alias": "gway-004", "known_hosts": str(self.known),
                "identity_file": str(self.identity),
                "host_key_sha256": OLD_DIGEST, "remote_user": "gway-relay",
            }],
        }))
        self.known.write_text("gway-004 " + OLD_PUBLIC + "\n")
        self.identity.write_bytes(b"synthetic fixture, not a credential")
        self.host.write_text(HOST_PUBLIC + "\n")
        for path in (self.config, self.known, self.identity, self.host):
            path.chmod(0o600)
        trusted_file, trusted_dir = pin._file, pin._directory
        self._patch(pin, "_file",
                    lambda path, *, uid, maximum, private=False:
                    trusted_file(path, uid=self.uid, maximum=maximum,
                                 private=private))
        self._patch(pin, "_directory",
                    lambda path, *, owner=None:
                    trusted_dir(path, owner=self.uid if owner == 0 else owner))
        self._patch(pin.os, "geteuid", lambda: 0)
        self._patch(pin, "CONFIG", self.config)

    def _patch(self, obj, name, value):
        p = patch.object(obj, name, value)
        p.start()
        self.addCleanup(p.stop)

    def _allow(self):
        self._patch(pin, "snapshot_from_path", lambda _: fake_ledger())
        self._patch(pin.node_registry_inventory, "load", lambda _: fake_inventory())

    def _transaction(self):
        before_config, before_known = self.config.read_bytes(), self.known.read_bytes()
        new_config = before_config + b"\n"
        new_known = before_known + b"gway-002 " + HOST_PUBLIC.encode() + b"\n"
        data = {
            "config": (self.config, before_config, new_config, self.config.stat()),
            "known": (self.known, before_known, new_known, self.known.stat()),
        }
        self._patch(pin, "plan", lambda *, service_uid: data)
        return self.root / "transaction", before_config, before_known

    def test_preview_is_read_only_and_binds_host_to_ledger(self):
        self._allow()
        report = pin.plan(service_uid=self.uid, config=self.config,
                          host_key=self.host, inventory=self.root / "snapshot")
        self.assertEqual(report["pin_digest"], HOST_DIGEST)
        self.assertEqual(report["existing_nodes"], ("gway-004",))
        self.assertIn(b"gway-002", report["known"][2])
        self.assertEqual(report["config"][1], self.config.read_bytes())
        self.assertEqual(report["known"][1], self.known.read_bytes())
        self.host.write_text(OLD_PUBLIC + "\n")
        with self.assertRaisesRegex(ValueError, "differs"):
            pin.plan(service_uid=self.uid, config=self.config,
                     host_key=self.host, inventory=self.root / "snapshot")

    def test_abb_preview_binds_named_attested_host_and_preserves_existing(self):
        ledger = fake_ledger()
        ledger['nodes'][0]['node'] = pin.ABB_NODE
        ledger['nodes'][0]['host_identity']['node'] = pin.ABB_NODE
        inventory = fake_inventory()
        inventory['nodes'][0]['node'] = pin.ABB_NODE
        self._patch(pin, 'snapshot_from_path', lambda _: ledger)
        self._patch(pin.node_registry_inventory, 'load', lambda _: inventory)
        report = pin.plan(service_uid=self.uid, config=self.config,
                          host_key=self.host, node=pin.ABB_NODE)
        self.assertEqual(report['existing_nodes'], ('gway-004',))
        self.assertIn(b'ocpp-abb-1 ', report['known'][2])
        self.assertEqual(report['known'][1], self.known.read_bytes())
        inventory['nodes'][0]['execute_eligible'] = False
        with self.assertRaisesRegex(pin.PinRefused, 'eligibility'):
            pin.plan(service_uid=self.uid, config=self.config,
                     host_key=self.host, node=pin.ABB_NODE)
        with self.assertRaisesRegex(pin.PinRefused, 'unsupported'):
            pin.plan(service_uid=self.uid, config=self.config,
                     host_key=self.host, node='ocpp-abb-2')

    def test_abb_transaction_uses_separate_authorization_and_rollback(self):
        before_config, before_known = self.config.read_bytes(), self.known.read_bytes()
        data = {'config': (self.config, before_config, before_config + b'\n', self.config.stat()),
                'known': (self.known, before_known, before_known + b'ocpp-abb-1 ' + HOST_PUBLIC.encode() + b'\n', self.known.stat())}
        self._patch(pin, 'plan', lambda *, service_uid, node: data)
        state = self.root / 'abb-transaction'
        with self.assertRaisesRegex(pin.PinRefused, 'explicit relay'):
            pin.apply(service_uid=self.uid, approval=pin._APPROVAL, relay_confirmed=True, state=state, node=pin.ABB_NODE)
        self.assertEqual(pin.apply(service_uid=self.uid, approval=pin.ABB_APPROVAL, relay_confirmed=True, state=state, node=pin.ABB_NODE), 'pending_acceptance')
        self.assertEqual(json.loads((state / 'journal.json').read_text())['node'], pin.ABB_NODE)
        with self.assertRaises(pin.PinRefused):
            pin.recover(state=state, approval='I_ACCEPT_GWAY_002_PIN_ROLLBACK', node=pin.ABB_NODE)
        self.assertEqual(pin.recover(state=state, approval=pin.ABB_ROLLBACK, node=pin.ABB_NODE), 'rolled_back')
        self.assertEqual(self.config.read_bytes(), before_config)
        self.assertEqual(self.known.read_bytes(), before_known)

    def test_preview_refuses_denied_grant_duplicate_and_drift(self):
        self._patch(pin, "snapshot_from_path", lambda _: fake_ledger())
        denied = fake_inventory()
        denied["nodes"][0]["execute_eligible"] = False
        p = patch.object(pin.node_registry_inventory, "load", return_value=denied)
        p.start()
        with self.assertRaisesRegex(ValueError, "eligibility"):
            pin.plan(service_uid=self.uid, config=self.config, host_key=self.host)
        p.stop()
        self._allow()
        self.known.write_text(self.known.read_text() + "gway-002 " + HOST_PUBLIC + "\n")
        with self.assertRaisesRegex(ValueError, "existing gway-002"):
            pin.plan(service_uid=self.uid, config=self.config, host_key=self.host)
        self.known.write_text("gway-004 " + HOST_PUBLIC + "\n")
        with self.assertRaisesRegex(ValueError, "pin is no longer valid"):
            pin.plan(service_uid=self.uid, config=self.config, host_key=self.host)

    def test_apply_requires_explicit_operator_assertion_and_preserves_backups(self):
        state, old_config, old_known = self._transaction()
        with self.assertRaisesRegex(pin.PinRefused, "explicit relay"):
            pin.apply(service_uid=self.uid, approval="", relay_confirmed=True, state=state)
        self.assertFalse(state.exists())
        self.assertEqual(pin.apply(service_uid=self.uid, approval=pin._APPROVAL,
                                  relay_confirmed=True, state=state),
                         "pending_acceptance")
        self.assertEqual((state / "config.before").read_bytes(), old_config)
        self.assertEqual((state / "known.before").read_bytes(), old_known)
        self.assertNotEqual(self.config.read_bytes(), old_config)
        self.assertNotEqual(self.known.read_bytes(), old_known)
        self.assertEqual(json.loads((state / "journal.json").read_text())["state"],
                         "pending_acceptance")
        with self.assertRaises(FileExistsError):
            pin.apply(service_uid=self.uid, approval=pin._APPROVAL,
                      relay_confirmed=True, state=state)
        self.assertEqual(pin.recover(
            state=state, approval="I_ACCEPT_GWAY_002_PIN_ROLLBACK"), "rolled_back")
        self.assertEqual(self.config.read_bytes(), old_config)
        self.assertEqual(self.known.read_bytes(), old_known)
        self.assertEqual(pin.recover(
            state=state, approval="I_ACCEPT_GWAY_002_PIN_ROLLBACK"), "already_rolled_back")

    def test_failure_between_swaps_recovers_exact_original_bytes(self):
        state, old_config, old_known = self._transaction()
        original_atomic = pin._atomic_file
        attempts = []

        def fail_second(path, raw, info):
            attempts.append(path.name)
            if len(attempts) == 2:
                raise OSError("synthetic interruption before second swap")
            return original_atomic(path, raw, info)

        self._patch(pin, "_atomic_file", fail_second)
        with self.assertRaisesRegex(OSError, "synthetic interruption"):
            pin.apply(service_uid=self.uid, approval=pin._APPROVAL,
                      relay_confirmed=True, state=state)
        self.assertEqual(self.config.read_bytes(), old_config)
        self.assertEqual(self.known.read_bytes(), old_known)
        self.assertEqual(json.loads((state / "journal.json").read_text())["state"],
                         "rolled_back")

    def test_external_edit_between_swaps_is_not_overwritten(self):
        state, old_config, _ = self._transaction()
        original_atomic = pin._atomic_file

        def edit_after_first_swap(path, raw, info):
            original_atomic(path, raw, info)
            if path == self.known:
                # External operator edits execute.json after the known_hosts
                # replacement, but before execute.json's own swap.
                self.config.write_bytes(b'{"operator":"new state"}')
                self.config.chmod(0o600)

        self._patch(pin, "_atomic_file", edit_after_first_swap)
        with self.assertRaisesRegex(pin.PinRefused,
                                    "concurrent change before target replacement"):
            pin.apply(service_uid=self.uid, approval=pin._APPROVAL,
                      relay_confirmed=True, state=state)
        self.assertEqual(self.config.read_bytes(), b'{"operator":"new state"}')
        self.assertNotEqual(self.config.read_bytes(), old_config)
        # The journal remains available for manual reconciliation, never
        # overwrite external bytes to force a rollback.
        self.assertEqual(json.loads((state / "journal.json").read_text())["state"],
                         "prepared")

    def test_recover_refuses_to_overwrite_unrelated_operator_changes(self):
        state, _, _ = self._transaction()
        pin.apply(service_uid=self.uid, approval=pin._APPROVAL,
                  relay_confirmed=True, state=state)
        self.config.write_bytes(b'{"unrelated":"operator change"}')
        self.config.chmod(0o600)
        with self.assertRaisesRegex(pin.PinRefused, "concurrent"):
            pin.recover(state=state, approval="I_ACCEPT_GWAY_002_PIN_ROLLBACK")
        self.assertEqual(self.config.read_bytes(), b'{"unrelated":"operator change"}')
        self.assertEqual(json.loads((state / "journal.json").read_text())["state"],
                         "pending_acceptance")


if __name__ == "__main__":
    unittest.main()
