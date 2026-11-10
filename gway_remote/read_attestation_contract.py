"""Offline-only read SSH attestation receipt verification.

This module neither loads a trust anchor nor enables any Watchtower transport.
The caller must independently supply a trusted verifier key and revocation set.
"""
import hashlib
import hmac
import json
import re
import time
import ipaddress

_FIELDS = frozenset({"schema", "issuer", "key_id", "node", "address",
                     "host_key_sha256", "ssh_principal", "identity_key_sha256",
                     "force_command_sha256", "issued_at", "expires_at",
                     "serial", "signature"})
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_NODE = re.compile(r"[a-z][a-z0-9-]{1,62}\Z")


def canonical_payload(receipt):
    return json.dumps({k: receipt[k] for k in sorted(_FIELDS - {"signature"})},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


MAX_RECEIPT_BYTES = 4096


def parse_read_receipt(raw):
    """Strict offline JSON boundary; no trust decisions or side effects."""
    if type(raw) is not bytes or not 2 <= len(raw) <= MAX_RECEIPT_BYTES:
        raise ValueError("invalid receipt size or encoding")
    try:
        decoded = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("invalid receipt UTF-8") from exc

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate receipt JSON key")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError("nonfinite JSON value")

    try:
        receipt = json.loads(decoded, object_pairs_hook=unique_pairs,
                             parse_constant=reject_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("invalid receipt JSON") from exc
    if type(receipt) is not dict or set(receipt) != _FIELDS:
        raise ValueError("invalid receipt JSON schema")
    if any(type(v) not in (str, int) for v in receipt.values()):
        raise ValueError("invalid receipt JSON field type")
    if type(receipt["issued_at"]) is not int or type(receipt["expires_at"]) is not int:
        raise ValueError("invalid receipt timestamps")
    return receipt


def verify_read_receipt(receipt, *, trusted_keys, revoked_serials, expected,
                        now=None):
    """Return verified claims, or fail closed; never trust caller's attested flag.

    trusted_keys maps (issuer, key_id) to independently provisioned HMAC keys.
    This is a local test contract, NOT an installed issuer or credential loader.
    expected binds node/address/host key/principal/identity key/ForceCommand.
    """
    if type(receipt) is not dict or set(receipt) != _FIELDS:
        raise ValueError("invalid read attestation receipt schema")
    if receipt["schema"] != "gway-read-attestation/v1":
        raise ValueError("unsupported receipt schema")
    for key in ("issuer", "key_id", "node", "address", "ssh_principal", "serial"):
        if type(receipt[key]) is not str or not receipt[key] or len(receipt[key]) > 128:
            raise ValueError("invalid read attestation identity")
    if any(not receipt[key].isascii() or any(ord(c) < 33 or ord(c) > 126 for c in receipt[key])
           for key in ("issuer", "key_id", "node", "address", "ssh_principal", "serial")):
        raise ValueError("noncanonical receipt identity")
    if not _NODE.fullmatch(receipt["node"]):
        raise ValueError("invalid attested node")
    try:
        address = ipaddress.ip_address(receipt["address"])
    except ValueError as exc:
        raise ValueError("invalid pinned read address") from exc
    if not isinstance(address, ipaddress.IPv4Address) or not address.is_private:
        raise ValueError("untrusted pinned read address")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", receipt["ssh_principal"]):
        raise ValueError("invalid SSH read principal")
    for key in ("host_key_sha256", "identity_key_sha256", "force_command_sha256", "signature"):
        if type(receipt[key]) is not str or not _HEX.fullmatch(receipt[key]):
            raise ValueError("invalid receipt digest")
    issued, expires = receipt["issued_at"], receipt["expires_at"]
    if type(issued) is not int or type(expires) is not int:
        raise ValueError("invalid receipt validity")
    current = int(time.time()) if now is None else now
    if type(current) is not int or issued < 0 or expires <= issued or issued > current or expires <= current or expires - issued > 86400:
        raise PermissionError("read attestation expired or not yet valid")
    if (type(revoked_serials) not in (set, frozenset)
            or any(type(item) is not str for item in revoked_serials)
            or receipt["serial"] in revoked_serials):
        raise PermissionError("revoked or untrusted read receipt")
    if type(expected) is not dict or set(expected) != {
        "node", "address", "host_key_sha256", "ssh_principal",
        "identity_key_sha256", "force_command_sha256"
    }:
        raise ValueError("incomplete expected pinned read identity")
    if any(type(value) is not str or receipt[k] != value for k, value in expected.items()):
        raise PermissionError("read receipt does not match pinned identity")
    key = trusted_keys.get((receipt["issuer"], receipt["key_id"])) if type(trusted_keys) is dict else None
    if type(key) is not bytes or len(key) < 32:
        raise PermissionError("no independently trusted receipt issuer")
    mac = hmac.new(key, canonical_payload(receipt), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, receipt["signature"]):
        raise PermissionError("invalid read attestation signature")
    return {key: receipt[key] for key in expected}
