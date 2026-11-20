"""Deterministic WireGuard port fake; no host, network or privilege access."""

from gway_remote.watchtower_enrollment import EnrollmentFailure, WireGuard


class MemoryWireGuard(WireGuard):
    def __init__(self, *, fail_set=False, confirm=True, refuse_removal=False):
        self.peers = {}
        self.fail_set = fail_set
        self.confirm = confirm
        self.refuse_removal = refuse_removal

    def set_peer(self, public_key, address):
        if self.fail_set:
            raise EnrollmentFailure("fake wg failure")
        self.peers[public_key] = address

    def has_peer(self, public_key, address):
        return self.confirm and self.peers.get(public_key) == address

    def remove_peer(self, public_key):
        if self.refuse_removal:
            raise AssertionError("fail-forward must not remove peers")
        self.peers.pop(public_key, None)
