"""Offline tests for short-lived Watchtower bootstrap sessions."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest

from gway_remote.watchtower_enrollment import EnrollmentRejected, Ledger


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "enrollment.sqlite3", network="10.90.0.0/24",
                  gateway="10.90.0.1")


def test_registration_url_is_separate_from_invitation_and_metadata_has_no_secrets(ledger):
    issued = ledger.register("gway-004", public_url="https://register.gelectriic.com")
    secret = issued["url"].rsplit("/", 1)[-1]
    assert urlsplit(issued["url"]).query == ""
    assert ledger.bootstrap_session(secret)["device"] == "gway-004"
    assert secret not in str(ledger.bootstrap_status())
    with ledger._connect() as conn:
        invitation = conn.execute("SELECT token_hash FROM invitations").fetchone()[0]
        session = conn.execute("SELECT session_hash FROM bootstrap_sessions").fetchone()[0]
    assert invitation != session
    assert secret not in (invitation, session)


def test_revoke_blocks_session_and_invitation(ledger):
    issued = ledger.register("gway-004", public_url="https://register.gelectriic.com")
    secret = issued["url"].rsplit("/", 1)[-1]
    assert ledger.revoke_bootstrap(issued["id"])
    assert not ledger.revoke_bootstrap(issued["id"])
    with pytest.raises(EnrollmentRejected):
        ledger.bootstrap_session(secret)


def test_expired_session_rejected(ledger):
    issued = ledger.register("gway-004", public_url="https://register.gelectriic.com", minutes=1)
    secret = issued["url"].rsplit("/", 1)[-1]
    with ledger._transaction() as conn:
        conn.execute("UPDATE bootstrap_sessions SET expires_at=? WHERE id=?",
                     ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(), issued["id"]))
    with pytest.raises(EnrollmentRejected):
        ledger.bootstrap_session(secret)


@pytest.mark.parametrize("origin", [
    "http://register.gelectriic.com", "https://evil.example",
    "https://register.gelectriic.com/?leak=1",
    "https://user@register.gelectriic.com",
    "https://register.gelectriic.com:8443",
])
def test_refuse_unsafe_registration_origin(ledger, origin):
    with pytest.raises(ValueError):
        ledger.register("gway-004", public_url=origin)
    assert ledger.bootstrap_status() == []


def test_bootstrap_enroll_retry_completion_and_replay(ledger, tmp_path):
    from gway_remote.watchtower_enrollment import Provisioner, WireGuard

    class FakeWireGuard(WireGuard):
        def __init__(self):
            self.peers = {}

        def set_peer(self, public_key, address):
            self.peers[public_key] = address

        def has_peer(self, public_key, address):
            return self.peers.get(public_key) == address

        def remove_peer(self, public_key):
            raise AssertionError("fail-forward must not remove peers")

    config = tmp_path / "hub.conf"
    config.write_text("[Interface]\\nAddress = 10.90.0.1/24\\n")
    provisioner = Provisioner(ledger, config, tmp_path / "backups", FakeWireGuard())
    issued = ledger.register("gway-004", public_url="https://register.gelectriic.com")
    secret = issued["url"].rsplit("/", 1)[-1]
    public_key = "A" * 43 + "="
    initial = provisioner.enroll("gway-004", public_key, secret)
    retry = provisioner.enroll("gway-004", public_key, secret)
    assert retry.already_active
    assert retry.address == initial.address
    assert ledger.bootstrap_session(secret)["device"] == "gway-004"
    assert ledger.complete_bootstrap(secret, "gway-004", public_key)
    assert not ledger.complete_bootstrap(secret, "gway-004", public_key)
    with pytest.raises(EnrollmentRejected):
        ledger.bootstrap_session(secret)
    with pytest.raises(EnrollmentRejected):
        provisioner.enroll("gway-004", public_key, secret)
    assert config.read_text().count("# BEGIN gway-remote enrollment: gway-004") == 1


def test_bootstrap_url_remains_bound_to_invited_node(ledger, tmp_path):
    from gway_remote.watchtower_enrollment import Provisioner, WireGuard

    class Noop(WireGuard):
        pass

    config = tmp_path / "hub.conf"
    config.write_text("[Interface]\\nAddress = 10.90.0.1/24\\n")
    issued = ledger.register("gway-004", public_url="https://register.gelectriic.com")
    token = issued["url"].rsplit("/", 1)[-1]
    provisioner = Provisioner(ledger, config, tmp_path / "backups", Noop())
    with pytest.raises(EnrollmentRejected):
        provisioner.enroll("gway-005", "A" * 43 + "=", token)
    assert ledger.status()["devices"] == 0


def test_http_bootstrap_flow_and_no_store(ledger, tmp_path, monkeypatch):
    import base64
    import json
    import threading
    from http.client import HTTPConnection
    from http.server import ThreadingHTTPServer
    from subprocess import CompletedProcess
    from gway_remote import watchtower_enrollment as wt

    class Fake(wt.WireGuard):
        def __init__(self):
            self.peers = {}

        def set_peer(self, key, address):
            self.peers[key] = address

        def has_peer(self, key, address):
            return self.peers.get(key) == address

        def remove_peer(self, key):
            raise AssertionError("unexpected peer deletion")

    key = base64.b64encode(bytes(range(32))).decode()
    hub_key = base64.b64encode(bytes(range(1, 33))).decode()
    monkeypatch.setattr(wt.subprocess, "run", lambda args, **kwargs: CompletedProcess(args, 0, hub_key + "\\n", ""))
    config = tmp_path / "hub.conf"
    config.write_text("[Interface]\\nAddress = 10.90.0.1/24\\n")
    provisioner = wt.Provisioner(ledger, config, tmp_path / "backups", Fake())
    invitation = ledger.register("gway-004", public_url="https://register.gelectriic.com")
    secret = invitation["url"].rsplit("/", 1)[-1]
    prefix = "/v1/bootstrap/" + secret
    handler = wt.make_handler(provisioner, public_url="https://register.gelectriic.com",
                              wireguard_endpoint="register.gelectriic.com:51820")
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        def request(method, route, body=None):
            conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            conn.request(method, route, body=body,
                         headers={"Content-Type": "application/json"})
            response = conn.getresponse()
            result = (response.status, dict(response.getheaders()), response.read())
            conn.close()
            return result

        status, headers, script = request("GET", prefix)
        assert status == 200
        assert headers["Cache-Control"] == "no-store"
        assert b"wireguard-tools" in script
        assert b"gway-004" in script
        assert b"/v1/enroll" not in script
        assert b"curl" in script
        assert b"apt-get" in script

        status, headers, client = request("GET", prefix + "/client.py")
        assert status == 200
        assert b"def bootstrap(" in client

        payload = json.dumps({"device": "gway-004", "public_key": key, "token": secret})
        status, _, reply = request("POST", "/v1/enroll", payload)
        assert status == 200
        assert json.loads(reply)["server_public_key"] == hub_key

        status, _, _ = request("POST", prefix + "/complete",
                               json.dumps({"device": "gway-004", "public_key": key}))
        assert status == 200
        status, _, _ = request("GET", prefix)
        assert status == 404
        status, _, _ = request("POST", "/v1/enroll", payload)
        assert status == 403
    finally:
        server.shutdown()
        server.server_close()
