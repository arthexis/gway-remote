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
