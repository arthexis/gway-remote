"""Hermetic transaction/restart and HTTP contracts for Watchtower replacement."""
import base64
import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch
from urllib.parse import urlsplit

from gway_remote.watchtower_enrollment import (
    EnrollmentFailure, EnrollmentRejected, Ledger, Provisioner, WireGuard,
    SubprocessWireGuard, make_handler,
)
from gway_remote.watchtower_replacement import PROTOCOL


def key(value):
    return base64.b64encode(bytes([value]) * 32).decode()


OLD, NEW, OTHER, UNMANAGED = (key(value) for value in range(1, 5))
ORIGINAL = (f"[Interface]\nAddress = 10.90.0.1/24\n\n[Peer]\n"
            f"# unmanaged peer retained verbatim\nPublicKey = {UNMANAGED}\nAllowedIPs = 10.90.0.2/32\n")


class PowerLoss(BaseException):
    pass


class FakeWireGuard(WireGuard):
    def __init__(self):
        self.peers = {UNMANAGED: ("10.90.0.2/32",)}
        self.handshakes = {}
        self.events = []

    def peer_snapshot(self):
        return dict(self.peers)

    def latest_handshake(self, public_key):
        return self.handshakes.get(public_key, 0)

    def has_peer(self, public_key, address):
        return self.peers.get(public_key) == (address,)

    def set_peer(self, public_key, address):
        # Assert the actual safety invariant on every simulated runtime write.
        assert all(address not in addresses for k, addresses in self.peers.items() if k != public_key)
        self.peers[public_key] = (address,)
        self.events.append(("set", public_key))

    def remove_peer(self, public_key):
        self.peers.pop(public_key, None)
        self.events.append(("remove", public_key))


class ReplacementFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / "gway.conf"
        self.config.write_text(ORIGINAL)
        self.wg = FakeWireGuard()
        self.restart()
        self.initial = self.p.enroll("gway-005", OLD, self.ledger.invite("gway-005")["token"])
        self.before = self.config.read_text()
        self.before_peers = dict(self.wg.peers)
        self.wg.events.clear()

    def restart(self):
        self.ledger = Ledger(self.root / "ledger.sqlite3", network="10.90.0.0/24", gateway="10.90.0.1")
        self.p = Provisioner(self.ledger, self.config, self.root / "backups", self.wg)
        self.r = self.p.replacements

    def session(self, device="gway-005", **kwargs):
        invitation = self.ledger.register(device, public_url="https://register.gelectriic.com", **kwargs)
        return invitation, urlsplit(invitation["url"]).path.rsplit("/", 1)[-1]

    def prepare(self, secret=None, public_key=NEW, **kwargs):
        if secret is None:
            _, secret = self.session(replace=True)
        with patch("gway_remote.watchtower_replacement.time.time", return_value=1000):
            receipt = self.r.prepare(secret, "gway-005", public_key, **kwargs)
        return secret, receipt

    def acknowledge(self, secret, receipt):
        self.wg.handshakes[receipt["public_key"]] = 1001
        with patch("gway_remote.watchtower_replacement.time.time", return_value=1002):
            return self.r.acknowledge(secret, "gway-005", receipt["public_key"], receipt["operation_id"])

    def active(self):
        with self.ledger._connect() as db:
            return dict(db.execute("SELECT * FROM devices WHERE device='gway-005'").fetchone())

    def reset_fixture(self):
        self.tmp.cleanup()
        self.setUp()


class ReplacementTests(ReplacementFixture, unittest.TestCase):

    def test_rekey_keeps_old_peer_until_verified_ack_and_retains_single_active_node(self):
        secret, prepared = self.prepare()
        self.assertEqual(self.active()["public_key"], OLD)
        self.assertEqual(prepared["state"], "prepared")
        self.assertNotEqual(prepared["address"], self.initial.address)
        self.assertIn(OLD, self.wg.peers)
        self.assertIn(NEW, self.wg.peers)
        self.assertNotIn(("remove", OLD), self.wg.events)
        committed = self.acknowledge(secret, prepared)
        self.assertEqual(committed["state"], "committed")
        self.assertTrue(committed["old_peer_retired"])
        self.assertEqual(self.active()["public_key"], NEW)
        self.assertEqual(self.active()["address"], prepared["address"])
        self.assertNotIn(OLD, self.wg.peers)
        self.assertIn(NEW, self.wg.peers)
        self.assertIn(ORIGINAL, self.config.read_text())
        self.assertEqual(self.config.read_text().count("# BEGIN gway-remote enrollment: gway-005"), 1)
        self.assertNotIn("# BEGIN gway-remote replacement:", self.config.read_text())
        self.assertEqual(self.ledger.status()["devices"], 1)
        self.assertEqual(self.ledger.status()["pending_operations"], 0)
        backup = next((self.root / "backups").glob("replacement-*.conf"))
        self.assertEqual(backup.read_text(), self.before)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)

    def test_same_key_revalidates_without_any_peer_or_address_change(self):
        secret, prepared = self.prepare(public_key=OLD)
        self.assertFalse(prepared["rekey"])
        self.assertEqual(prepared["address"], self.initial.address)
        self.assertEqual(self.config.read_text(), self.before)
        self.assertEqual(self.wg.events, [])
        result = self.acknowledge(secret, prepared)
        self.assertFalse(result["old_peer_retired"])
        self.assertEqual(self.config.read_text(), self.before)
        self.assertEqual(self.wg.peers, self.before_peers)

    def test_retries_are_bound_and_completed_invitation_cannot_prepare_again(self):
        secret, first = self.prepare()
        _, repeat = self.prepare(secret)
        self.assertEqual(first["operation_id"], repeat["operation_id"])
        for device, public_key in (("gway-004", NEW), ("gway-005", OTHER)):
            with self.assertRaises(EnrollmentRejected):
                self.r.prepare(secret, device, public_key)
        committed = self.acknowledge(secret, first)
        events = list(self.wg.events)
        self.assertEqual(self.acknowledge(secret, first), committed)
        self.assertEqual(self.r.status(secret, "gway-005", NEW, first["operation_id"]), committed)
        with self.assertRaises(EnrollmentRejected):
            self.r.prepare(secret, "gway-005", NEW)
        with self.assertRaises(EnrollmentRejected):
            self.r.rollback(secret, "gway-005", NEW, first["operation_id"])
        with self.assertRaises(EnrollmentRejected):
            self.ledger.bootstrap_session(secret)
        self.assertEqual(self.wg.events, events)

    def test_ordinary_repair_raw_invitation_and_legacy_completion_cannot_replace(self):
        _, ordinary = self.session()
        with self.assertRaises(EnrollmentRejected):
            self.r.prepare(ordinary, "gway-005", NEW)
        with self.ledger._transaction() as db:
            db.execute("UPDATE invitations SET revoked_at='revoked' WHERE consumed_at IS NULL")
        _, repair = self.session(repair_host_identity=True)
        with self.assertRaises(EnrollmentRejected):
            self.r.prepare(repair, "gway-005", NEW)
        with self.ledger._transaction() as db:
            db.execute("UPDATE invitations SET revoked_at='revoked' WHERE consumed_at IS NULL")
        _, secret = self.session(replace=True)
        with self.assertRaises(EnrollmentRejected):
            self.p.enroll("gway-005", OLD, secret)
        with self.assertRaises(EnrollmentRejected):
            self.ledger.complete_bootstrap(secret, "gway-005", OLD)
        with self.assertRaises(ValueError):
            self.ledger.invite("gway-006", purpose="host_identity_repair", replace=True)
        self.assertEqual(self.wg.peers, self.before_peers)
        self.assertEqual(self.config.read_text(), self.before)

    def test_ack_requires_a_new_fresh_nonfuture_handshake(self):
        secret, prepared = self.prepare()
        for stamp in (0, 999, 1000, 2000):
            with self.subTest(stamp=stamp):
                self.wg.handshakes[NEW] = stamp
                with patch("gway_remote.watchtower_replacement.time.time", return_value=1002):
                    with self.assertRaises(EnrollmentRejected):
                        self.r.acknowledge(secret, "gway-005", NEW, prepared["operation_id"])
                self.assertIn(OLD, self.wg.peers)
        self.wg.handshakes[NEW] = 1001
        with patch("gway_remote.watchtower_replacement.time.time", return_value=1400):
            with self.assertRaises(EnrollmentRejected):
                self.r.acknowledge(secret, "gway-005", NEW, prepared["operation_id"])

    def test_rollback_is_idempotent_releases_allocation_and_preserves_unrelated_edits(self):
        secret, prepared = self.prepare()
        self.config.write_text(self.config.read_text() + "# unrelated operator comment\n")
        result = self.r.rollback(secret, "gway-005", NEW, prepared["operation_id"])
        self.assertEqual(result["state"], "rolled_back")
        self.assertEqual(self.config.read_text(), self.before + "# unrelated operator comment\n")
        self.assertEqual(self.wg.peers, self.before_peers)
        self.assertEqual(self.active()["public_key"], OLD)
        self.assertEqual(self.ledger.status()["pending_operations"], 0)
        self.assertEqual(self.r.rollback(secret, "gway-005", NEW, prepared["operation_id"]), result)
        _, second = self.prepare()
        self.assertEqual(prepared["address"], second["address"])

    def test_revoked_or_expired_preparation_rolls_back_on_restart(self):
        for reason in ("revoked", "expired"):
            with self.subTest(reason=reason):
                invitation, secret = self.session(replace=True)
                _, prepared = self.prepare(secret)
                if reason == "revoked":
                    self.assertTrue(self.ledger.revoke_bootstrap(invitation["id"]))
                else:
                    with self.ledger._transaction() as db:
                        db.execute("UPDATE invitations SET expires_at='2000-01-01' WHERE id=(SELECT invitation_id FROM bootstrap_sessions WHERE id=?)", (invitation["id"],))
                with self.assertRaises(EnrollmentRejected):
                    self.r.acknowledge(secret, "gway-005", NEW, prepared["operation_id"])
                self.restart()
                self.assertEqual(self.p.recover(), 1)
                self.assertEqual(self.wg.peers, self.before_peers)
                self.assertEqual(self.config.read_text(), self.before)
                self.assertEqual(self.ledger.status()["pending_operations"], 0)

    def test_prepare_power_loss_before_and_after_every_side_effect_recovers(self):
        for target, name in (("manager", "_backup"), ("provisioner", "_write"),
                             ("wireguard", "set_peer"), ("manager", "_advance")):
            for after in (False, True):
                with self.subTest(target=target, name=name, after=after):
                    _, secret = self.session(replace=True)
                    obj = {"manager": self.r, "provisioner": self.p, "wireguard": self.wg}[target]
                    original = getattr(obj, name)
                    def fail(*args, **kwargs):
                        if after:
                            original(*args, **kwargs)
                        raise PowerLoss()
                    with patch.object(obj, name, side_effect=fail):
                        with self.assertRaises(PowerLoss):
                            self.prepare(secret)
                    self.assertIn(OLD, self.wg.peers)
                    self.restart()
                    self.p.recover()
                    with self.ledger._connect() as db:
                        op = dict(db.execute("SELECT * FROM replacements WHERE session_hash=(SELECT session_hash FROM bootstrap_sessions WHERE id=(SELECT id FROM bootstrap_sessions ORDER BY rowid DESC LIMIT 1))").fetchone())
                    self.assertEqual(op["state"], "prepared")
                    self.r.rollback(secret, "gway-005", NEW, op["id"])
                    self.assertEqual(self.wg.peers, self.before_peers)
                    self.assertEqual(self.config.read_text(), self.before)

    def test_ack_power_loss_replays_durable_commit_after_file_and_runtime_changes(self):
        # Each case starts a new replacement, and then rolls the test fixture back.
        for target, name, after in (("manager", "_commit", False),
                                    ("provisioner", "_write", True),
                                    ("wireguard", "remove_peer", False),
                                    ("wireguard", "remove_peer", True),
                                    ("manager", "_commit", True)):
            with self.subTest(target=target, name=name, after=after):
                secret, prepared = self.prepare()
                obj = {"manager": self.r, "provisioner": self.p, "wireguard": self.wg}[target]
                original = getattr(obj, name)
                def fail(*args, **kwargs):
                    if after:
                        original(*args, **kwargs)
                    raise PowerLoss()
                with patch.object(obj, name, side_effect=fail):
                    with self.assertRaises(PowerLoss):
                        self.acknowledge(secret, prepared)
                self.restart()
                self.p.recover()
                result = self.acknowledge(secret, prepared)
                self.assertEqual(result["state"], "committed")
                self.assertEqual(self.active()["public_key"], NEW)
                self.assertNotIn(OLD, self.wg.peers)
                self.assertEqual(self.ledger.status()["pending_operations"], 0)
                # Independent fixture, without manipulating production paths.
                self.reset_fixture()

    def test_rollback_power_loss_retries_without_an_orphan_peer_or_allocation(self):
        for target, name in (("provisioner", "_write"), ("wireguard", "remove_peer")):
            for after in (False, True):
                with self.subTest(target=target, after=after):
                    secret, prepared = self.prepare()
                    obj = self.p if target == "provisioner" else self.wg
                    original = getattr(obj, name)
                    def fail(*args, **kwargs):
                        if after:
                            original(*args, **kwargs)
                        raise PowerLoss()
                    with patch.object(obj, name, side_effect=fail):
                        with self.assertRaises(PowerLoss):
                            self.r.rollback(secret, "gway-005", NEW, prepared["operation_id"])
                    self.restart()
                    self.p.recover()
                    self.assertEqual(self.config.read_text(), self.before)
                    self.assertEqual(self.wg.peers, self.before_peers)
                    self.assertEqual(self.ledger.status()["pending_operations"], 0)

    def test_unmanaged_peer_config_drift_and_conflicting_key_are_never_modified(self):
        for fault in ("unmanaged", "runtime_drift", "owned_block"):
            with self.subTest(fault=fault):
                _, secret = self.session(replace=True)
                if fault == "unmanaged":
                    candidate = UNMANAGED
                else:
                    candidate = NEW
                    if fault == "runtime_drift":
                        self.wg.peers[UNMANAGED] = ("10.90.0.9/32",)
                    else:
                        self.config.write_text(self.config.read_text().replace("# Device = gway-005", "# manually changed"))
                before, peers = self.config.read_text(), dict(self.wg.peers)
                with self.assertRaises((EnrollmentRejected, EnrollmentFailure)):
                    self.prepare(secret, public_key=candidate)
                self.assertEqual(self.config.read_text(), before)
                self.assertEqual(self.wg.peers, peers)
                self.reset_fixture()

    def test_two_nodes_and_parallel_preparations_preserve_other_peers_and_addresses(self):
        other_initial = self.p.enroll("gway-006", OTHER, self.ledger.invite("gway-006")["token"])
        secret, prepared = self.prepare()
        # Ordinary enrollment is also serialized and cannot allocate the staged /32.
        third = self.p.enroll("gway-007", key(6), self.ledger.invite("gway-007")["token"])
        self.assertNotEqual(third.address, prepared["address"])
        self.acknowledge(secret, prepared)
        self.assertEqual(self.wg.peers[OTHER], (other_initial.address,))
        self.assertEqual(self.wg.peers[key(6)], (third.address,))
        self.assertEqual(self.wg.peers[UNMANAGED], ("10.90.0.2/32",))
        self.assertEqual(self.ledger.status()["devices"], 3)

    def test_concurrent_identical_prepare_is_one_operation(self):
        _, secret = self.session(replace=True)
        results, failures = [], []
        def run():
            try:
                # Separate provisioners do not share the Python lock. This
                # exercises the same file lock used across service processes.
                p = Provisioner(self.ledger, self.config, self.root / "backups", self.wg)
                results.append(p.replacements.prepare(secret, "gway-005", NEW))
            except Exception as exc:
                failures.append(type(exc).__name__)
        threads = [threading.Thread(target=run) for _ in range(4)]
        for worker in threads:
            worker.start()
        for worker in threads:
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(len({r["operation_id"] for r in results}), 1)
        self.assertEqual(self.ledger.status()["pending_operations"], 1)

    def test_two_replacement_transactions_commit_and_rollback_independently(self):
        initial = self.p.enroll("gway-006", OTHER, self.ledger.invite("gway-006")["token"])
        first_secret, first = self.prepare()
        _, second_secret = self.session("gway-006", replace=True)
        second = self.r.prepare(second_secret, "gway-006", key(7))
        self.assertNotEqual(first["address"], second["address"])
        self.acknowledge(first_secret, first)
        self.assertEqual(self.wg.peers[OTHER], (initial.address,))
        self.assertEqual(self.wg.peers[key(7)], (second["address"],))
        self.r.rollback(second_secret, "gway-006", key(7), second["operation_id"])
        self.assertEqual(self.wg.peers[NEW], (first["address"],))
        self.assertEqual(self.wg.peers[OTHER], (initial.address,))
        self.assertNotIn(key(7), self.wg.peers)
        self.assertEqual(self.ledger.status()["pending_operations"], 0)

    def test_accepted_ack_is_recovered_after_expiry_and_cannot_be_revoked_mid_commit(self):
        issued, secret = self.session(replace=True)
        _, prepared = self.prepare(secret)
        with patch.object(self.r, "_commit", side_effect=PowerLoss):
            with self.assertRaises(PowerLoss):
                self.acknowledge(secret, prepared)
        self.assertFalse(self.ledger.revoke_bootstrap(issued["id"]))
        with self.ledger._transaction() as db:
            db.execute("UPDATE invitations SET expires_at='2000-01-01' WHERE id=(SELECT invitation_id FROM bootstrap_sessions WHERE id=?)", (issued["id"],))
        self.restart()
        self.assertEqual(self.p.recover(), 1)
        self.assertEqual(self.active()["public_key"], NEW)
        self.assertNotIn(OLD, self.wg.peers)
        self.assertEqual(self.ledger.status()["pending_operations"], 0)

    def test_external_candidate_address_change_blocks_commit_and_peer_removal(self):
        secret, prepared = self.prepare()
        self.wg.peers[NEW] = ("10.90.0.99/32",)
        self.wg.handshakes[NEW] = 1001
        before = self.config.read_text()
        with self.assertRaises(EnrollmentFailure):
            self.acknowledge(secret, prepared)
        self.assertEqual(self.config.read_text(), before)
        self.assertIn(OLD, self.wg.peers)
        self.assertNotIn(("remove", OLD), self.wg.events)

    def test_host_binding_is_preserved_and_revocation_or_substitution_blocks(self):
        wire = bytes((0, 0, 0, 11)) + b"ssh-ed25519" + bytes((0, 0, 0, 32)) + bytes(range(32))
        host = "ssh-ed25519 " + base64.b64encode(wire).decode()
        with self.ledger._transaction() as db:
            db.execute("INSERT INTO host_identities VALUES(?,?,?,?,?,'active',?,?)",
                       ("gway-005", self.initial.operation_id, OLD, host, "original-binding", "created", "2999-01-01"))
        _, secret = self.session(replace=True)
        for supplied in (None, "ssh-ed25519 substituted"):
            with self.assertRaises(EnrollmentRejected):
                self.prepare(secret, ssh_host_key=supplied)
        _, prepared = self.prepare(secret, ssh_host_key=host)
        self.acknowledge(secret, prepared)
        with self.ledger._connect() as db:
            identity = dict(db.execute("SELECT * FROM host_identities").fetchone())
        self.assertEqual(identity["host_public_key"], host)
        self.assertEqual(identity["wireguard_identity"], NEW)
        self.assertEqual(identity["created_at"], "created")
        self.assertEqual(identity["valid_until"], "2999-01-01")
        self.assertTrue(self.ledger.revoke_host_identity("gway-005"))
        _, next_secret = self.session(replace=True)
        with self.assertRaises(EnrollmentRejected):
            self.prepare(next_secret, public_key=OTHER, ssh_host_key=host)

    def test_unknown_host_binding_is_not_created_by_replacement(self):
        _, secret = self.session(replace=True)
        with self.assertRaises(EnrollmentRejected):
            self.prepare(secret, ssh_host_key="ssh-ed25519 untrusted")
        _, prepared = self.prepare(secret)
        self.acknowledge(secret, prepared)
        with self.ledger._connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM host_identities").fetchone()[0], 0)

    def test_damaged_backup_or_unrelated_runtime_drift_blocks_without_snapshot_restore(self):
        secret, prepared = self.prepare()
        backup = next((self.root / "backups").glob("replacement-*.conf"))
        backup.write_text("damaged")
        before, peers = self.config.read_text(), dict(self.wg.peers)
        with self.assertRaises(EnrollmentFailure):
            self.p.recover()
        self.assertEqual(self.config.read_text(), before)
        self.assertEqual(self.wg.peers, peers)


class ReplacementHTTPTests(ReplacementFixture, unittest.TestCase):
    def test_http_exact_authorization_protocol_replay_and_sanitized_errors(self):
        issued, secret = self.session(replace=True)
        handler = make_handler(self.p, public_url="https://register.gelectriic.com",
                               wireguard_endpoint="register.gelectriic.com:51820")
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join, 3)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        prefix = "/v1/bootstrap/" + secret
        def request(method, route, data=None):
            conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            try:
                conn.request(method, route, body=(json.dumps(data) if isinstance(data, dict) else data),
                             headers={"Content-Type": "application/json"})
                response = conn.getresponse()
                return response.status, dict(response.getheaders()), response.read()
            finally:
                conn.close()
        with patch("gway_remote.watchtower_enrollment.subprocess.run",
                   return_value=CompletedProcess([], 0, key(9) + "\n", "")):
            for query in ("", "?replace=false", "?replace=True", "?replace=true&replace=true", "?replace=%74rue", "?replace=true&repair=true"):
                self.assertEqual(request("GET", prefix + query)[0], 404)
            status, headers, script = request("GET", prefix + "?replace=true")
            self.assertEqual(status, 200)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertIn(b"--replace --replacement-protocol gway-replace-v1", script)
            self.assertNotIn(b"/complete", script)
            self.assertIn(b"hostname -s", script)
            self.assertEqual(request("GET", prefix + "/client.py")[0], 404)
            self.assertEqual(request("GET", prefix + "/client.py?replace=true")[0], 200)
            body = {"protocol": PROTOCOL, "device": "gway-005", "public_key": NEW}
            route = prefix + "/replacement/prepare?replace=true"
            for bad in ({**body, "repair": True}, {**body, "protocol": "unknown"}, {**body, "device": "gway-006"}):
                status, _, raw = request("POST", route, bad)
                self.assertIn(status, (400, 403))
                self.assertNotIn(secret.encode(), raw)
                self.assertNotIn(NEW.encode(), raw)
            self.assertEqual(request("POST", route, '{"protocol":"gway-replace-v1","protocol":"gway-replace-v1"}')[0], 400)
            with patch("gway_remote.watchtower_replacement.time.time", return_value=1000):
                status, _, raw = request("POST", route, body)
            self.assertEqual(status, 200)
            prepared = json.loads(raw)
            ack = {**body, "operation_id": prepared["operation_id"], "activated": True}
            self.assertEqual(request("POST", prefix + "/replacement/ack?replace=true", ack)[0], 403)
            self.wg.handshakes[NEW] = 1001
            with patch("gway_remote.watchtower_replacement.time.time", return_value=1002):
                self.assertEqual(request("POST", prefix + "/replacement/ack?replace=true", ack)[0], 200)
            self.assertEqual(request("GET", prefix + "?replace=true")[0], 404)
            self.assertEqual(request("POST", route, body)[0], 403)
            self.assertEqual(request("POST", prefix + "/replacement/ack?replace=true", ack)[0], 200)
        self.assertEqual(self.ledger.status()["pending_operations"], 0)


class WireGuardReplacementObservationTests(unittest.TestCase):
    def test_zipapp_initializes_replacement_ledger_with_packaged_module(self):
        import shutil
        import subprocess
        import sys
        import zipapp
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            shutil.copytree(Path(__file__).resolve().parents[2] / "gway_remote", source / "gway_remote",
                            ignore=shutil.ignore_patterns("__pycache__"))
            (source / "__main__.py").write_text(
                "import json,sys\nfrom pathlib import Path\n"
                "from gway_remote.watchtower_enrollment import Ledger\n"
                "print(json.dumps(Ledger(Path(sys.argv[1]),network='10.90.0.0/24',gateway='10.90.0.1').status()))\n")
            archive = root / "remote.pyz"
            zipapp.create_archive(source, archive)
            result = subprocess.run([sys.executable, str(archive), str(root / "ledger.sqlite3")],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {"invitations": 0, "devices": 0, "pending_operations": 0})

    def test_snapshot_and_handshake_use_only_narrow_observation_commands(self):
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            output = (OLD + "\t1001\n" if args[-1] == "latest-handshakes"
                      else OLD + "\t10.90.0.3/32, 10.90.0.4/32\n")
            return CompletedProcess(args, 0, output, "")
        wg = SubprocessWireGuard(runner=run)
        self.assertEqual(wg.peer_snapshot()[OLD], ("10.90.0.3/32", "10.90.0.4/32"))
        self.assertEqual(wg.latest_handshake(OLD), 1001)
        self.assertEqual(wg.latest_handshake(NEW), 0)
        self.assertTrue(all(call[:3] == ["wg", "show", "gway"] for call in calls))
