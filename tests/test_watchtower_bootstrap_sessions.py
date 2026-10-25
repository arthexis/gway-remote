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
