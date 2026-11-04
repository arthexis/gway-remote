"""Isolated B2 WebAuthn cryptographic verifier.

No HTTP/CLI/MCP entry points and NO bearer/secret issuance. Uses Duo Labs'
audited py_webauthn. The verifier intentionally has no registration write
capability: C must provide a trusted, independently approved enrollment flow.
"""
import base64
from dataclasses import dataclass

from .watchtower_webauthn_ledger import _check_identifier

RP_ID = "remote.arthexis.com"
ORIGIN = "https://remote.arthexis.com"
MAX_CREDENTIAL_JSON = 16384


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _validate_credential(credential):
    if not isinstance(credential, dict) or len(str(credential)) > MAX_CREDENTIAL_JSON:
        raise ValueError("invalid_credential")
    # Don't accept caller-chosen remote origins. py_webauthn performs the
    # canonical clientDataJSON and authenticatorData verification.
    if credential.get("type") != "public-key" or not isinstance(credential.get("response"), dict):
        raise ValueError("invalid_credential")
    return credential


@dataclass(frozen=True)
class VerifiedRegistration:
    credential_id: str
    public_key: bytes
    sign_count: int


@dataclass(frozen=True)
class VerifiedAssertion:
    credential_id: str
    sign_count: int


def verify_registration(ledger, *, challenge, principal, credential):
    """Verify a passkey creation; NEVER persist it or authorize enrollment.

    Registration is restricted to the passkey.enroll intent. Later C must
    independently check an existing administrator-approved bootstrap grant
    before invoking the restricted ledger persistence sink.
    """
    from webauthn import verify_registration_response
    from webauthn.helpers import base64url_to_bytes
    principal = _check_identifier(principal)
    if not ledger.consume(challenge=challenge, principal=principal,
                          action="passkey.enroll", target=principal):
        raise ValueError("invalid_or_expired_intent")
    result = verify_registration_response(
        credential=_validate_credential(credential),
        expected_challenge=base64url_to_bytes(challenge),
        expected_rp_id=RP_ID, expected_origin=ORIGIN,
        require_user_verification=True,
    )
    return VerifiedRegistration(
        credential_id=_b64url(result.credential_id),
        public_key=result.credential_public_key,
        sign_count=result.sign_count,
    )


def verify_assertion(ledger, *, challenge, principal, action, target, credential):
    """Verify a stored passkey assertion; return proof data, NOT a permission.

    The one-use action-bound intent is burned BEFORE cryptographic validation.
    An independent privileged service in C must bind the proof to its
    authenticated request, enforce authorization, and consume it atomically
    with the privileged operation. Never treat this result as an access token.
    """
    from webauthn import verify_authentication_response
    from webauthn.helpers import base64url_to_bytes
    principal = _check_identifier(principal)
    target = _check_identifier(target)
    if not ledger.consume(challenge=challenge, principal=principal,
                          action=action, target=target):
        raise ValueError("invalid_or_expired_intent")
    credential = _validate_credential(credential)
    cid = credential.get("id")
    if not isinstance(cid, str) or len(cid) > 128:
        raise ValueError("invalid_credential_id")
    raw_id = base64url_to_bytes(cid)
    if not raw_id or _b64url(raw_id) != cid:
        raise ValueError("invalid_credential_id")
    row = ledger._verified_credential(credential_id=cid, principal=principal)
    if row is None:
        raise ValueError("unknown_or_revoked_credential")
    public_key, old_count = row
    result = verify_authentication_response(
        credential=credential, expected_challenge=base64url_to_bytes(challenge),
        expected_rp_id=RP_ID, expected_origin=ORIGIN,
        credential_public_key=public_key,
        credential_current_sign_count=old_count,
        require_user_verification=True,
    )
    ledger._advance_verified_counter(
        credential_id=cid, principal=principal,
        previous=old_count, current=result.new_sign_count)
    return VerifiedAssertion(credential_id=cid, sign_count=result.new_sign_count)
