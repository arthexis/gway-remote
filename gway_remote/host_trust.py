"""Explicit, restricted host-key pinning from authenticated Watchtower evidence.

Never run from SSH host-key discovery. Caller must supply a snapshot fetched through
the independently pinned Watchtower forced-command SSH identity.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

from .host_identity import HostIdentityError, validate_attestation
from .node_inspection import resolve_target


def verified_host_identity(snapshot, node, approved, *, now=None):
    address = resolve_target(snapshot, node, approved)
    matches = [entry for entry in snapshot["nodes"]
               if isinstance(entry, dict) and entry.get("node") == node]
    if len(matches) != 1:
        raise HostIdentityError("ambiguous host identity")
    record = matches[0].get("host_identity")
    identity = validate_attestation(record, node=node, now=now)
    # Both keys must identify the same enrollment operation in Watchtower.
    wg = matches[0].get("wireguard_identity")
    if wg is None or wg != identity["wireguard_identity"]:
        raise HostIdentityError("Watchtower enrollment key binding missing")
    return address, identity


def pin_from_snapshot(snapshot, node, approved, path, *, authorize_initial=False,
                      now=None):
    """Pin only to a dedicated, existing private file.

    First pin requires explicit operator approval AND authenticated registry
    evidence. No automatic rotation; the existing host-key line is immutable.
    No generic known_hosts or SSH configuration files are ever modified.
    """
    _, identity = verified_host_identity(snapshot, node, approved, now=now)
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise HostIdentityError("dedicated known-hosts file unavailable")
    if path.stat().st_uid != os.geteuid() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise HostIdentityError("known-hosts file must be private and owned by caller")
    from .inspection_ssh_trust import _trusted_parent_directories
    _trusted_parent_directories(path)
    alias = identity["host_key_alias"]
    expected = alias + " " + identity["host_key"]
    # Never overwrite entries or follow unexpected mappings.
    with path.open("r+", encoding="ascii") as handle:
        import fcntl
        fcntl.flock(handle, fcntl.LOCK_EX)
        lines = [line.strip() for line in handle if line.strip()]
        pinned = [line for line in lines if line.split()[0] == alias]
        if pinned:
            if len(pinned) != 1 or pinned[0] != expected:
                raise HostIdentityError("pinned identity mismatch; rotation approval required")
            return False
        if not authorize_initial:
            raise HostIdentityError("initial pin requires explicit authorization")
        handle.seek(0, os.SEEK_END)
        handle.write(("\n" if lines else "") + expected + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return True


def pin_from_watchtower(node, approved, path, *, authorize_initial=False,
                        ssh_config=None):
    """Resolve authoritative snapshot via Bastion-pinned Watchtower SSH."""
    from .watchtower_inspection_client import SSH_CONFIG, fetch_snapshot
    config = ssh_config or SSH_CONFIG
    snapshot = fetch_snapshot(config=config)
    address, identity = verified_host_identity(snapshot, node, approved)
    from .inspection_ssh_trust import validate_profile
    validate_profile(config, node, hostname=address, require_jump=True,
                     host_key_alias=identity["host_key_alias"],
                     expected_known_hosts=path)
    return pin_from_snapshot(snapshot, node, approved, path,
                             authorize_initial=authorize_initial)
