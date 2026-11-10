"""Offline-only authority boundary for read receipts; no production implementation.

A verifier's successful HMAC check is not authorization to use a receipt.
The authority must validate current issuer/key/serial revocation and identity binding using
independently trusted state. Reusing an unchanged valid receipt is allowed.
"""
from .read_attestation_contract import parse_read_receipt, verify_read_receipt


class ReadReceiptAuthorityUnavailable(PermissionError):
    """No independently trusted authority was configured."""


class ReadReceiptAuthority:
    """Contract only: read-only check of current authoritative revocation state.

    validate_attestation() may accept the same unchanged signed receipt more
    than once. It must reject revoked issuer/key/serial, stale revocation data,
    or a serial bound to a different signed receipt. No backend is installed.
    """
    def validate_attestation(self, *, issuer, key_id, serial, expires_at, node,
                             receipt_digest):
        raise ReadReceiptAuthorityUnavailable("read receipt authority unavailable")


def authorize_read_receipt(raw, *, trusted_keys, expected, authority=None, now=None):
    """Fail closed; never fall back to execute transport or an in-memory ledger."""
    if authority is None or type(authority) is ReadReceiptAuthority:
        raise ReadReceiptAuthorityUnavailable("read receipt authority unavailable")
    if not isinstance(authority, ReadReceiptAuthority):
        raise TypeError("untrusted read receipt authority")
    receipt = parse_read_receipt(raw)
    # Authority owns authoritative revocation checks; this empty set is NOT
    # revocation evidence and does not authorize the receipt.
    claims = verify_read_receipt(receipt, trusted_keys=trusted_keys,
                                 revoked_serials=set(), expected=expected, now=now)
    import hashlib
    from .read_attestation_contract import canonical_payload
    decision = authority.validate_attestation(issuer=receipt["issuer"], key_id=receipt["key_id"],
                                 serial=receipt["serial"], expires_at=receipt["expires_at"],
                                 node=receipt["node"],
                                 receipt_digest=hashlib.sha256(canonical_payload(receipt)).hexdigest())
    if decision is not True:
        raise ReadReceiptAuthorityUnavailable("read receipt not authorized")
    return claims
