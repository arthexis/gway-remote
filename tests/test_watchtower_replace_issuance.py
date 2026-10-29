"""Server-side authorization contract for replacement URL issuance."""
from urllib.parse import urlsplit

import pytest

from gway_remote.watchtower_enrollment import Ledger, EnrollmentRejected


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "ledger.sqlite3", network="10.90.0.0/24", gateway="10.90.0.1")


def test_replace_url_has_server_side_authorization(ledger):
    issued = ledger.register("gway-005", public_url="https://register.gelectriic.com", replace=True)
    assert urlsplit(issued["url"]).query == "replace=true"
    assert ledger.bootstrap_session(urlsplit(issued["url"]).path.rsplit("/", 1)[-1])["replace"] is True
    with ledger._connect() as db:
        row = db.execute("SELECT purpose, replace_authorized FROM invitations").fetchone()
    assert row["purpose"] == "enroll"
    assert row["replace_authorized"] == 1


def test_normal_url_does_not_grant_replacement(ledger):
    issued = ledger.register("gway-005", public_url="https://register.gelectriic.com")
    assert urlsplit(issued["url"]).query == ""
    assert ledger.bootstrap_session(issued["url"].rsplit("/", 1)[-1])["replace"] is False


def test_replace_cannot_combine_with_host_identity_repair(ledger):
    with pytest.raises(ValueError):
        ledger.register("gway-005", public_url="https://register.gelectriic.com",
                        repair_host_identity=True, replace=True)
    assert ledger.bootstrap_status() == []


def test_legacy_ledger_is_migrated_without_rebuilding(tmp_path):
    import sqlite3
    from gway_remote.watchtower_enrollment import SCHEMA
    path = tmp_path / "legacy.sqlite3"
    legacy = SCHEMA.replace(
        ",\n    replace_authorized INTEGER NOT NULL DEFAULT 0 CHECK(replace_authorized IN (0,1))", "")
    with sqlite3.connect(path) as db:
        db.executescript(legacy)
    ledger = Ledger(path, network="10.90.0.0/24", gateway="10.90.0.1")
    with ledger._connect() as db:
        assert "replace_authorized" in {row["name"] for row in db.execute("PRAGMA table_info(invitations)")}
