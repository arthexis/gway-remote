"""Offline-only authority boundary for read receipts; no production implementation.

A verifier's successful HMAC check is not authorization to use a receipt.
The authority must atomically check issuer/key/serial uniqueness, current
revocation state and replay policy against independently trusted durable state.
"""
from .read_attestation_contract import parse_read_receipt, verify_read_receipt


class ReadReceiptAuthorityUnavailable(PermissionError):
    """No independently trusted authority was configured."""


class ReadReceiptAuthority:
    """Contract only: implement with authenticated, durable atomic storage.

    consume() must reject reused serials, revoked issuers/keys/serials, stale
    revocation data, and concurrent duplicate consumption; never return a
    positive result without durable commit. No default authority is installed.
    """
    def consume(self, *, issuer, key_id, serial, expires_at, node):
        raise ReadReceiptAuthorityUnavailable("read receipt authority unavailable")


def authorize_read_receipt(raw, *, trusted_keys, expected, authority=None, now=None):
    """Fail closed; never fall back to execute transport or an in-memory ledger."""
    if authority is None or type(authority) is ReadReceiptAuthority:
        raise ReadReceiptAuthorityUnavailable("read receipt authority unavailable")
    if not isinstance(authority, ReadReceiptAuthority):
        raise TypeError("untrusted read receipt authority")
    receipt = parse_read_receipt(raw)
    # A durable authority must own authoritative revocation checks; this empty
    # set is NOT a revocation check and does not authorize consumption.
    claims = verify_read_receipt(receipt, trusted_keys=trusted_keys,
                                 revoked_serials=set(), expected=expected, now=now)
    decision = authority.consume(issuer=receipt["issuer"], key_id=receipt["key_id"],
                                 serial=receipt["serial"], expires_at=receipt["expires_at"],
                                 node=receipt["node"])
    if decision is not True:
        raise ReadReceiptAuthorityUnavailable("read receipt not authorized")
    return claims
