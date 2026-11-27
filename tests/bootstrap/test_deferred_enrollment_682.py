"""Proof-of-possession deferred card enrollment, no network or hardware."""
import base64
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from gway_remote.deferred_enrollment import (
    DeferredPreparations, PreparationRejected, proof_message,
)


@pytest.fixture
def e(tmp_path):
    db = tmp_path / "watchtower.db"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
        CREATE TABLE devices(device TEXT PRIMARY KEY,state TEXT);
        CREATE TABLE invitations(
          id TEXT PRIMARY KEY,device TEXT,token_hash TEXT,expires_at TEXT,
          consumed_at TEXT,revoked_at TEXT,purpose TEXT);
        CREATE UNIQUE INDEX single_invitation ON invitations(device)
          WHERE consumed_at IS NULL AND revoked_at IS NULL;
        CREATE TABLE bootstrap_sessions(
          id TEXT PRIMARY KEY,session_hash TEXT,invitation_id TEXT,device TEXT,
          expires_at TEXT,revoked_at TEXT);
        """)
    now = [datetime(2026,11,23,tzinfo=timezone.utc)]
    ledger = DeferredPreparations(db, sealing_key=Fernet.generate_key(),clock=lambda: now[0])
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return ledger, key, base64.urlsafe_b64encode(pub).decode().rstrip("="), now


def sign(ledger,key,ident):
    nonce = ledger.challenge(ident)
    signature = base64.urlsafe_b64encode(
        key.sign(proof_message(ident,"gway-014",nonce))).decode().rstrip("=")
    return nonce, signature


def test_claim_and_signed_idempotent_retry(e):
    ledger,key,pub,now = e
    ident = ledger.prepare("gway-014",pub)["id"]
    n,s = sign(ledger,key,ident)
    result = ledger.claim(ident,n,s)
    assert result["bootstrap_url"].startswith("https://register.gelectriic.com/v1/bootstrap/")
    with pytest.raises(PreparationRejected):
        ledger.claim(ident,n,s)
    n2,s2 = sign(ledger,key,ident)
    retry = ledger.claim(ident,n2,s2)
    assert retry["bootstrap_url"] == result["bootstrap_url"]
    assert retry["claim_expires_at"] == result["claim_expires_at"]
    assert "public_key" not in ledger.status(ident)


def test_wrong_signing_key_and_challenge_expiry(e):
    ledger,key,pub,now = e
    ident = ledger.prepare("gway-014",pub)["id"]
    nonce = ledger.challenge(ident)
    wrong = Ed25519PrivateKey.generate()
    sig = base64.urlsafe_b64encode(wrong.sign(
        proof_message(ident,"gway-014",nonce))).decode().rstrip("=")
    with pytest.raises(PreparationRejected):
        ledger.claim(ident,nonce,sig)
    n,s = sign(ledger,key,ident)
    now[0] += timedelta(minutes=3)
    with pytest.raises(PreparationRejected):
        ledger.claim(ident,n,s)


def test_expiration_reissue_and_no_reuse(e):
    ledger,key,pub,now = e
    ident = ledger.prepare("gway-014",pub,hours=1)["id"]
    now[0] += timedelta(hours=1)
    with pytest.raises(PreparationRejected):
        ledger.challenge(ident)
    assert ledger.prepare("gway-014",pub)["id"] != ident
    with pytest.raises(PreparationRejected):
        ledger.prepare("gway-014",pub)


def test_claim_near_expiration_has_full_two_hours(e):
    ledger,key,pub,now = e
    ident = ledger.prepare("gway-014",pub)["id"]
    now[0] += timedelta(hours=23,minutes=59)
    n,s = sign(ledger,key,ident)
    result = ledger.claim(ident,n,s)
    assert datetime.fromisoformat(result["claim_expires_at"]) == now[0]+timedelta(hours=2)


def test_revoke_revokes_bootstrap_and_invitation(e):
    ledger,key,pub,now = e
    ident = ledger.prepare("gway-014",pub)["id"]
    n,s = sign(ledger,key,ident)
    result = ledger.claim(ident,n,s)
    assert ledger.revoke(ident)
    assert not ledger.revoke(ident)
    with pytest.raises(PreparationRejected):
        ledger.challenge(ident)
    with sqlite3.connect(ledger.path) as db:
        assert db.execute("SELECT revoked_at FROM bootstrap_sessions").fetchone()[0]
        assert db.execute("SELECT revoked_at FROM invitations").fetchone()[0]
        raw = str(db.execute("SELECT sealed_session FROM sd_preparations").fetchone()[0])
        assert result["bootstrap_url"].split("/")[-1] not in raw


def test_concurrent_claims_only_one_first_transition(e):
    ledger,key,pub,now = e
    ident = ledger.prepare("gway-014",pub)["id"]
    n,s = sign(ledger,key,ident)
    def run(_):
        try:
            ledger.claim(ident,n,s)
            return "ok"
        except PreparationRejected:
            return "rejected"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run,range(2))) == ["ok","rejected"]
    with sqlite3.connect(ledger.path) as db:
        assert db.execute("SELECT COUNT(*) FROM bootstrap_sessions").fetchone()[0] == 1


def test_existing_device_rejected(e):
    ledger,key,pub,now = e
    with sqlite3.connect(ledger.path) as db:
        db.execute("INSERT INTO devices VALUES('gway-014','active')")
    with pytest.raises(PreparationRejected):
        ledger.prepare("gway-014",pub)
