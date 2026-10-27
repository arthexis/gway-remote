"""Explicit after-the-fact host-attestation repair contracts."""
import base64
import sqlite3

import pytest

from gway_remote.watchtower_enrollment import EnrollmentRejected, Ledger, Provisioner, WireGuard


WIRE = base64.b64encode(bytes(range(32))).decode()
HOST = "ssh-ed25519 " + base64.b64encode(
    b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + bytes(range(32))
).decode()
OTHER_HOST = "ssh-ed25519 " + base64.b64encode(
    b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + bytes(range(1, 33))
).decode()


class NoMutationWireGuard(WireGuard):
    def set_peer(self, *_args):
        raise AssertionError("repair must not add or change a peer")

    def has_peer(self, *_args):
        raise AssertionError("repair must not inspect or change a peer")


def active_legacy_node(ledger):
    invitation = ledger.invite("gway-005")
    enrolled = ledger.reserve(device="gway-005", public_key=WIRE,
                              token=invitation["token"], occupied=set())
    ledger.advance(enrolled.operation_id, "committed")
    return enrolled


def test_repair_binds_first_host_identity_without_touching_peer_or_config(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3", network="10.90.0.0/24", gateway="10.90.0.1")
    original = active_legacy_node(ledger)
    config = tmp_path / "gway.conf"
    config.write_text("[Interface]\nAddress = 10.90.0.1/24\n")
    provisioner = Provisioner(ledger, config, tmp_path / "backups", NoMutationWireGuard())
    issued = ledger.register("gway-005", public_url="https://register.gelectriic.com",
                             repair_host_identity=True)
    secret = issued["url"].rsplit("/", 1)[-1]
    with pytest.raises(EnrollmentRejected):
        ledger.reserve(device="gway-005", public_key=WIRE, token=secret,
                       occupied=set())

    repaired = provisioner.repair_host_identity("gway-005", WIRE, secret,
                                                 ssh_host_key=HOST)

    assert repaired.address == original.address
    assert repaired.already_active
    assert config.read_text() == "[Interface]\nAddress = 10.90.0.1/24\n"
    with ledger._connect() as connection:
        peer = connection.execute("SELECT operation_id,address,state FROM devices WHERE device='gway-005'").fetchone()
        identity = connection.execute("SELECT wireguard_identity,state FROM host_identities WHERE device='gway-005'").fetchone()
        operation = connection.execute("SELECT state,detail FROM operations WHERE id=?", (repaired.operation_id,)).fetchone()
    assert tuple(peer) == (original.operation_id, original.address, "active")
    assert tuple(identity) == (WIRE, "active")
    assert tuple(operation) == ("committed", "host_identity_repair")
    assert ledger.complete_bootstrap(secret, "gway-005", WIRE)


def test_repair_rejects_normal_invitation_and_host_substitution(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3", network="10.90.0.0/24", gateway="10.90.0.1")
    active_legacy_node(ledger)
    normal = ledger.register("gway-005", public_url="https://register.gelectriic.com")
    normal_secret = normal["url"].rsplit("/", 1)[-1]
    with pytest.raises(EnrollmentRejected):
        ledger.repair_host_identity(device="gway-005", public_key=WIRE,
                                    token=normal_secret, ssh_host_key=HOST)
    assert ledger.revoke_bootstrap(normal["id"])

    issued = ledger.register("gway-005", public_url="https://register.gelectriic.com",
                             repair_host_identity=True)
    secret = issued["url"].rsplit("/", 1)[-1]
    ledger.repair_host_identity(device="gway-005", public_key=WIRE,
                                token=secret, ssh_host_key=HOST)
    retry = ledger.register("gway-005", public_url="https://register.gelectriic.com",
                            repair_host_identity=True)
    with pytest.raises(EnrollmentRejected):
        ledger.repair_host_identity(device="gway-005", public_key=WIRE,
                                    token=retry["url"].rsplit("/", 1)[-1],
                                    ssh_host_key=OTHER_HOST)


def test_existing_ledger_migrates_repair_purpose_without_rewriting_rows(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE invitations (id TEXT PRIMARY KEY, device TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE, expires_at TEXT NOT NULL, consumed_at TEXT, revoked_at TEXT)")
    ledger = Ledger(path, network="10.90.0.0/24", gateway="10.90.0.1")
    with ledger._connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(invitations)")}
    assert "purpose" in columns


def test_repair_bootstrap_http_flow_never_mutates_hub_peer_or_config(tmp_path, monkeypatch):
    import json
    import threading
    from http.client import HTTPConnection
    from http.server import ThreadingHTTPServer
    from subprocess import CompletedProcess

    from gway_remote import watchtower_enrollment as watchtower

    hub = base64.b64encode(bytes(range(1, 33))).decode()
    monkeypatch.setattr(
        watchtower.subprocess, "run",
        lambda args, **kwargs: CompletedProcess(args, 0, hub + "\n", ""),
    )
    ledger = Ledger(tmp_path / "ledger.sqlite3", network="10.90.0.0/24", gateway="10.90.0.1")
    active_legacy_node(ledger)
    config = tmp_path / "gway.conf"
    original = "[Interface]\nAddress = 10.90.0.1/24\n"
    config.write_text(original)
    provisioner = Provisioner(ledger, config, tmp_path / "backups", NoMutationWireGuard())
    issued = ledger.register("gway-005", public_url="https://register.gelectriic.com",
                             repair_host_identity=True)
    secret = issued["url"].rsplit("/", 1)[-1]
    handler = watchtower.make_handler(
        provisioner, public_url="https://register.gelectriic.com",
        wireguard_endpoint="register.gelectriic.com:51820",
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
        connection.request("GET", "/v1/bootstrap/" + secret)
        response = connection.getresponse()
        script = response.read()
        connection.close()
        assert response.status == 200
        assert b"--repair-host-identity" in script

        payload = json.dumps({"device": "gway-005", "public_key": WIRE,
                              "token": secret, "ssh_host_key": HOST,
                              "repair_host_identity": True})
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
        connection.request("POST", "/v1/enroll", body=payload,
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        body = json.loads(response.read())
        connection.close()
        assert response.status == 200
        assert body["repaired"] is True
        assert config.read_text() == original

        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
        connection.request("POST", "/v1/bootstrap/" + secret + "/complete",
                           body=json.dumps({"device": "gway-005", "public_key": WIRE}),
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        assert response.status == 200
        response.read()
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
