"""Behavioral parity guardrails for splitting the Watchtower enrollment owner.

Only a private SQLite ledger, temporary files and a loopback in-process server
are used. These cases cannot enroll real devices or touch a live WireGuard peer.
"""
from __future__ import annotations

import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import sqlite3
import threading

import pytest

from gway_remote import watchtower_enrollment as wt


def test_ledger_reserve_advance_records_and_commits_only_selected_node(ledger):
    secret = ledger.invite("gway-004")["token"]
    result = ledger.reserve(device="gway-004", public_key="A" * 43 + "=",
                            token=secret, occupied={"10.90.0.2/32"})
    assert result.address == "10.90.0.3/32"
    with ledger._connect() as db:
        assert db.execute("SELECT state FROM operations WHERE id=?",
                          (result.operation_id,)).fetchone()[0] == "reserved"
    assert ledger.status() == {"invitations": 1, "devices": 0, "pending_operations": 1}
    for state in ("config_written", "runtime_applied"):
        ledger.advance(result.operation_id, state)
        with ledger._connect() as db:
            assert db.execute("SELECT state FROM operations WHERE id=?",
                              (result.operation_id,)).fetchone()[0] == state
        assert ledger.status()["devices"] == 0
    ledger.advance(result.operation_id, "committed")
    assert ledger.status() == {"invitations": 0, "devices": 1, "pending_operations": 0}


def test_ledger_read_only_does_not_rewrite_sqlite(ledger):
    before = ledger.path.read_bytes()
    readonly = wt.Ledger(ledger.path, network="10.90.0.0/24",
                         gateway="10.90.0.1", read_only=True)
    assert readonly.status() == ledger.status()
    assert readonly.bootstrap_status() == []
    assert ledger.path.read_bytes() == before
    with pytest.raises(sqlite3.OperationalError):
        readonly.invite("gway-004")


def test_peer_renderer_is_byte_preserving_and_idempotent():
    original = "[Interface]\nAddress = 10.90.0.1/24\n\n[Peer]\n# outsider\nAllowedIPs = 10.90.0.2/32\n"
    enrolled = wt.Enrollment("operation", "gway-004", "A" * 43 + "=", "10.90.0.3/32")
    expected = (original + "# BEGIN gway-remote enrollment: gway-004\n"
                "[Peer]\n# Device = gway-004\n"
                "PublicKey = " + ("A" * 43 + "=") +
                "\nAllowedIPs = 10.90.0.3/32\n# END gway-remote enrollment: gway-004\n")
    assert wt.render_managed_peer(original, enrolled) == expected
    assert wt.render_managed_peer(expected, enrolled) == expected
    assert wt.occupied_addresses(original) == {"10.90.0.2/32"}


def test_readonly_http_health_and_enrollment_denial_are_stable():
    handler = wt.make_handler(None, public_url="https://register.gelectriic.com",
                              wireguard_endpoint="register.gelectriic.com:51820",
                              read_only_stage=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        def request(method, route, data=None):
            client = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            client.request(method, route, body=data,
                           headers={"Content-Type": "application/json"})
            reply = client.getresponse()
            result = (reply.status, dict(reply.getheaders()), reply.read())
            client.close()
            return result
        status, headers, payload = request("GET", "/health")
        assert status == 200
        assert headers["Cache-Control"] == "no-store"
        assert json.loads(payload)["ok"] is True
        status, headers, payload = request("GET", "/v1/bootstrap/" + "A" * 40)
        assert status == 404
        assert b"not_found" in payload
        status, headers, payload = request("POST", "/v1/enroll", b"{}")
        assert status == 400
        assert b"invalid_request" in payload
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def test_ledger_module_preserves_public_objects_by_identity():
    from gway_remote import watchtower_enrollment_ledger as module
    for name in ("Ledger", "Enrollment", "EnrollmentRejected",
                 "EnrollmentFailure", "SCHEMA"):
        assert getattr(wt, name) is getattr(module, name)


def test_enrollment_public_interface_remains_accessible():
    for name in ("Ledger", "Enrollment", "EnrollmentRejected", "EnrollmentFailure",
                 "SCHEMA", "WireGuard", "SubprocessWireGuard", "Provisioner",
                 "occupied_addresses", "render_managed_peer", "make_handler", "serve"):
        assert getattr(wt, name) is not None, name
