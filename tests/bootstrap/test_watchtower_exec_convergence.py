"""Pure central pin composition: no network, root writes or SSH private keys."""
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
import pytest

from gway_remote.watchtower_exec_convergence import _entry_and_bytes, ConvergenceRefused

RAW = bytes((0,0,0,11)) + b"ssh-ed25519" + bytes((0,0,0,32)) + bytes(range(32))
SSH = "ssh-ed25519 " + base64.b64encode(RAW).decode()
DIGEST = hashlib.sha256(RAW).hexdigest()
WG = base64.b64encode(bytes(range(32))).decode()
NOW = datetime.now(timezone.utc)
ENTRY = {"node": "gway-001", "address": "10.90.0.2",
         "ssh_host_alias": "gway-001", "known_hosts": "/private/known",
         "identity_file": "/private/key", "host_key_sha256": DIGEST,
         "remote_user": "gway-relay"}


def before():
    c = json.dumps({"enabled": True, "nodes": [dict(ENTRY)]}).encode()
    k = ("gway-001 " + SSH + "\n").encode()
    host = {"schema":1,"node":"gway-005","wireguard_identity":WG,
            "host_public_key":SSH,"enrollment_binding":"a"*64,
            "state":"active","rotation_state":"stable",
            "created_at":(NOW-timedelta(minutes=2)).isoformat(),
            "valid_until":(NOW+timedelta(days=7)).isoformat()}
    s = {"schema":2,"nodes":[{"node":"gway-005","state":"active",
                                "address":"10.90.0.5/32",
                                "host_identity":host}]}
    return c,k,s


def test_grant_is_pinned_by_existing_attested_identity_only():
    config, known, snapshot = before()
    future, known2 = _entry_and_bytes("gway-005", True, config, known, snapshot)
    j = json.loads(future)
    assert len(j["nodes"]) == 2
    assert j["nodes"][0] == ENTRY
    assert j["nodes"][-1]["host_key_sha256"] == DIGEST
    assert j["nodes"][-1]["remote_user"] == "gway-relay"
    assert known2.endswith(("gway-005 " + SSH + "\n").encode())
    assert _entry_and_bytes("gway-005", False, future, known2, snapshot)[0] == (
        json.dumps({"enabled":True,"nodes":[ENTRY]},
                   separators=(",",":"),sort_keys=True) + "\n").encode()


def test_pin_is_idempotent_and_stale_or_changed_key_is_refused():
    config, known, snapshot = before()
    next_config, next_known = _entry_and_bytes("gway-005", True, config, known, snapshot)
    assert _entry_and_bytes("gway-005", True, next_config, next_known, snapshot) == (
        next_config, next_known)
    snapshot["nodes"][0]["host_identity"]["host_public_key"] = "ssh-ed25519 " + base64.b64encode(
        RAW[:-1] + b"Z").decode()
    with pytest.raises(ConvergenceRefused):
        _entry_and_bytes("gway-005", True, next_config, next_known, snapshot)


def test_unattested_or_removed_node_is_denied():
    config, known, snapshot = before()
    snapshot["nodes"][0]["host_identity"]["state"] = "revoked"
    with pytest.raises(ValueError):
        _entry_and_bytes("gway-005", True, config, known, snapshot)
    snapshot["nodes"][0]["state"] = "revoked"
    assert _entry_and_bytes("gway-005", False, config, known, snapshot) == (
        config, known)


def test_unknown_preexisting_pin_is_not_replaced():
    config, known, snapshot = before()
    known += ("gway-005 ssh-ed25519 " + base64.b64encode(RAW[:-1]+b"Z").decode() + "\n").encode()
    with pytest.raises(ConvergenceRefused):
        _entry_and_bytes("gway-005", True, config, known, snapshot)


def test_revoke_only_other_transport_is_denied():
    config, known, snapshot = before()
    snapshot["nodes"][0]["node"] = "gway-001"
    with pytest.raises(ConvergenceRefused):
        _entry_and_bytes("gway-001", False, config, known, snapshot)

def test_revoke_works_for_inactive_previously_enrolled_node():
    config, known, snapshot = before()
    configured, pinned = _entry_and_bytes("gway-005", True, config, known, snapshot)
    snapshot["nodes"][0]["state"] = "revoked"
    reduced, pin_after = _entry_and_bytes("gway-005", False, configured, pinned, snapshot)
    assert len(json.loads(reduced)["nodes"]) == 1
    assert pin_after == pinned

def test_cas_updates_known_hosts_before_config_and_never_overwrites_edits(monkeypatch):
    import stat
    from pathlib import Path
    from types import SimpleNamespace
    from gway_remote import watchtower_exec_convergence as cv
    meta = SimpleNamespace(st_uid=0, st_gid=0, st_mode=stat.S_IFREG | 0o600, st_ino=19)
    contents = {"/tmp/known": b"known_old", "/tmp/execute": b"config_old"}
    records = {"known": (Path("/tmp/known"), b"known_old", b"known_new", meta),
               "config": (Path("/tmp/execute"), b"config_old", b"config_new", meta)}
    writes = []
    def read(path, **kwargs):
        return contents[str(path)], meta
    def apply(path, data, info):
        writes.append(str(path))
        contents[str(path)] = data
    monkeypatch.setattr(cv, "_file", read)
    monkeypatch.setattr(cv, "_atomic_file", apply)
    cv._activate_files(records)
    assert writes == ["/tmp/known", "/tmp/execute"]
    contents["/tmp/execute"] = b"foreign"
    with pytest.raises(cv.ConvergenceRefused):
        cv._activate_files(records)
    assert writes == ["/tmp/known", "/tmp/execute"]


def test_idempotent_grant_never_restarts_gateway_or_writes(monkeypatch, tmp_path):
    from pathlib import Path
    from types import SimpleNamespace
    from gway_remote import watchtower_exec_convergence as cv
    from gway_remote import node_registry_inventory
    tmp_path.chmod(0o700)
    path = Path("/tmp/example")
    same = (path, b"stable", b"stable", SimpleNamespace())
    monkeypatch.setattr(cv, "plan", lambda *a, **kw:
                        {"known": same, "config": same, "node": "gway-005"})
    monkeypatch.setattr(cv, "_directory", lambda *a, **kw: None)
    monkeypatch.setattr(cv.os, "geteuid", lambda: 0)
    monkeypatch.setattr(node_registry_inventory, "_grants",
                        lambda *_: {"gway-005": ("key", True)})
    def reject(*args, **kwargs):
        raise AssertionError("idempotent grant must have no side effects")
    result = cv.converge("grant", "gway-005", state_root=tmp_path,
                         set_grant=reject, publisher=reject, runner=reject)
    assert result["changed"] is False


def test_two_nodes_cannot_mutate_shared_pin_files_in_parallel(monkeypatch, tmp_path):
    from pathlib import Path
    from types import SimpleNamespace
    from gway_remote import watchtower_exec_convergence as cv
    from gway_remote import node_registry_inventory
    tmp_path.chmod(0o700)
    (tmp_path / ".active").mkdir(mode=0o700)
    changed = (Path("/tmp/config"), b"old", b"new", SimpleNamespace())
    monkeypatch.setattr(cv, "plan", lambda *a, **kw:
                        {"known": changed, "config": changed, "node": "gway-007"})
    monkeypatch.setattr(cv, "_directory", lambda *a, **kw: None)
    monkeypatch.setattr(cv.os, "geteuid", lambda: 0)
    monkeypatch.setattr(node_registry_inventory, "_grants", lambda *_: {})
    def reject(*args, **kwargs):
        raise AssertionError("no mutation before shared lock is acquired")
    with pytest.raises(FileExistsError):
        cv.converge("grant", "gway-007", state_root=tmp_path,
                    set_grant=reject, publisher=reject, runner=reject)

def test_strict_limits_uses_only_existing_unprivileged_gateway_identity():
    from subprocess import CompletedProcess
    from gway_remote.watchtower_exec_convergence import verify_gateway_limits
    observed = []
    def run(argv, **kwargs):
        observed.append(argv)
        return CompletedProcess(argv, 0,
                                json.dumps({"schema": 1, "node": "gway-005",
                                            "stage": "limits", "status": "succeeded",
                                            "concurrent_jobs_per_node": 3}), "")
    assert verify_gateway_limits("gway-005", runner=run) is True
    assert len(observed) == 1
    assert observed[0][:4] == ["/usr/bin/sudo", "-n", "-u", "gway-mcp-gateway"]
    assert observed[0][-4:] == ["node", "verify", "gway-005", "--json"]
    assert "ssh-keyscan" not in " ".join(observed[0])


@pytest.mark.parametrize("result", [
    {"schema": 1, "node": "gway-002", "stage": "limits",
     "status": "succeeded", "concurrent_jobs_per_node": 3},
    {"schema": 1, "node": "gway-005", "stage": "limits",
     "status": "failed", "concurrent_jobs_per_node": 3},
    {"schema": 1, "node": "gway-005", "stage": "limits",
     "status": "succeeded", "concurrent_jobs_per_node": True},
])
def test_wrong_or_failed_gateway_receipt_is_not_accepted(result):
    from subprocess import CompletedProcess
    from gway_remote.watchtower_exec_convergence import verify_gateway_limits
    def run(argv, **kwargs):
        return CompletedProcess(argv, 0, json.dumps(result), "")
    with pytest.raises(ConvergenceRefused):
        verify_gateway_limits("gway-005", runner=run)
