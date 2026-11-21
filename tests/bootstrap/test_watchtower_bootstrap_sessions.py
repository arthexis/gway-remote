"""Offline tests for short-lived Watchtower bootstrap sessions."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest

from gway_remote.watchtower_enrollment import EnrollmentRejected
from tests.bootstrap.fakes import MemoryWireGuard


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


def test_expired_completion_fails_even_after_peer_is_active(ledger, tmp_path):
    from gway_remote.watchtower_enrollment import Provisioner
    config = tmp_path / "hub.conf"
    config.write_text("[Interface]\\nAddress = 10.90.0.1/24\\n")
    provisioner = Provisioner(ledger, config, tmp_path / "backups",
                              MemoryWireGuard(refuse_removal=True))
    issued = ledger.register("gway-004", public_url="https://register.gelectriic.com")
    secret = issued["url"].rsplit("/", 1)[-1]
    key = "A" * 43 + "="
    provisioner.enroll("gway-004", key, secret)
    with ledger._transaction() as db:
        db.execute("UPDATE bootstrap_sessions SET expires_at=? WHERE id=?",
                   ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),
                    issued["id"]))
    with pytest.raises(EnrollmentRejected):
        ledger.complete_bootstrap(secret, "gway-004", key)


def test_repair_registration_is_marked_in_the_private_bootstrap_session(ledger):
    issued = ledger.register("gway-004", public_url="https://register.gelectriic.com",
                             repair_host_identity=True)
    secret = issued["url"].rsplit("/", 1)[-1]
    assert issued["repair_host_identity"] is True
    assert ledger.bootstrap_session(secret)["repair_host_identity"] is True


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
    from gway_remote.watchtower_enrollment import Provisioner

    config = tmp_path / "hub.conf"
    config.write_text("[Interface]\\nAddress = 10.90.0.1/24\\n")
    provisioner = Provisioner(ledger, config, tmp_path / "backups", MemoryWireGuard(refuse_removal=True))
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

    key = base64.b64encode(bytes(range(32))).decode()
    hub_key = base64.b64encode(bytes(range(1, 33))).decode()
    monkeypatch.setattr(wt.subprocess, "run", lambda args, **kwargs: CompletedProcess(args, 0, hub_key + "\n", ""))
    config = tmp_path / "hub.conf"
    config.write_text("[Interface]\\nAddress = 10.90.0.1/24\\n")
    provisioner = wt.Provisioner(ledger, config, tmp_path / "backups", MemoryWireGuard(refuse_removal=True))
    invitation = ledger.register("gway-004", public_url="https://register.gelectriic.com")
    secret = invitation["url"].rsplit("/", 1)[-1]
    prefix = "/v1/bootstrap/" + secret
    handler = wt.make_handler(provisioner, public_url="https://register.gelectriic.com",
                              wireguard_endpoint="register.gelectriic.com:51820",
                              release_provider=lambda: {
                                  "revision": "a" * 40, "client_sha256": "b" * 64,
                                  "relay_public_key": "ssh-ed25519 " + "A" * 43 + "="})
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

        stages = ["wireguard", "package", "user_manager", "restricted_relay", "receiver"]
        status, _, bad = request("POST", prefix + "/complete",
                                 json.dumps({"device": "gway-004", "public_key": key,
                                             "revision": "c" * 40, "stages": stages}))
        assert status == 400
        assert "invalid_request" in bad.decode()
        assert ledger.bootstrap_session(secret)["device"] == "gway-004"
        status, _, completed = request("POST", prefix + "/complete",
                                       json.dumps({"device": "gway-004", "public_key": key,
                                                   "revision": "a" * 40,
                                                   "stages": stages}))
        assert status == 200
        body = json.loads(completed)
        assert body["complete"] is True
        assert body["local_setup_reported"] is True
        assert body["local_ready_verified"] is False
        assert body["remote_execution_verified"] is False
        status, _, _ = request("GET", prefix)
        assert status == 404
        status, _, _ = request("POST", "/v1/enroll", payload)
        assert status == 403
    finally:
        server.shutdown()
        server.server_close()


def test_register_reissues_pending_named_host_without_replace_or_repair(ledger):
    first = ledger.register("ocpp-abb-1", public_url="https://register.gelectriic.com")
    first_secret = first["url"].rsplit("/", 1)[-1]
    second = ledger.register("ocpp-abb-1", public_url="https://register.gelectriic.com")
    second_secret = second["url"].rsplit("/", 1)[-1]
    assert first["id"] != second["id"]
    with pytest.raises(EnrollmentRejected):
        ledger.bootstrap_session(first_secret)
    assert ledger.bootstrap_session(second_secret)["device"] == "ocpp-abb-1"
    with ledger._connect() as conn:
        old = conn.execute("SELECT revoked_at FROM bootstrap_sessions WHERE id=?", (first["id"],)).fetchone()
        assert old["revoked_at"] is not None
        active = conn.execute(
            "SELECT COUNT(*) FROM invitations WHERE device=? AND revoked_at IS NULL AND consumed_at IS NULL",
            ("ocpp-abb-1",),
        ).fetchone()[0]
        assert active == 1
