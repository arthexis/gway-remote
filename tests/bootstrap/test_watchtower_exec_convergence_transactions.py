"""Hermetic tests for central grant serialization, CAS, limits and recovery."""
import json
import pytest

from gway_remote.watchtower_exec_convergence import ConvergenceRefused

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
    from subprocess import CompletedProcess
    def reject(*args, **kwargs):
        raise AssertionError("idempotent grant must have no side effects")
    def read_only_limits(argv, **kwargs):
        assert argv[:4] == ["/usr/bin/sudo", "-n", "-u", "gway-mcp-gateway"]
        return CompletedProcess(argv, 0, json.dumps({
            "schema": 1, "node": "gway-005", "stage": "limits",
            "status": "succeeded", "concurrent_jobs_per_node": 3}), "")
    result = cv.converge("grant", "gway-005", state_root=tmp_path,
                         set_grant=reject, publisher=reject, runner=read_only_limits)
    assert result["changed"] is False
    assert result["limits_verified"] is True


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


@pytest.mark.parametrize("action", ["grant", "revoke"])
def test_pending_global_lock_blocks_grant_and_revoke(monkeypatch, tmp_path, action):
    """Even an apparently idempotent grant may not bypass an unresolved journal."""
    from gway_remote import watchtower_exec_convergence as cv
    from gway_remote import node_registry_inventory
    tmp_path.chmod(0o700)
    (tmp_path / ".active").mkdir(mode=0o700)
    monkeypatch.setattr(cv.os, "geteuid", lambda: 0)
    monkeypatch.setattr(cv, "_directory", lambda *a, **kw: None)
    monkeypatch.setattr(node_registry_inventory, "_grants",
                        lambda *_: {"gway-005": ("key", True)})
    def reject(*args, **kwargs):
        raise AssertionError("planning or probing must not run before lock")
    monkeypatch.setattr(cv, "plan", reject)
    with pytest.raises(FileExistsError):
        cv.converge(action, "gway-005", state_root=tmp_path,
                    set_grant=reject, publisher=reject, runner=reject)


def test_planning_occurs_under_shared_lock_and_releases_on_refusal(monkeypatch, tmp_path):
    from gway_remote import watchtower_exec_convergence as cv
    tmp_path.chmod(0o700)
    monkeypatch.setattr(cv.os, "geteuid", lambda: 0)
    monkeypatch.setattr(cv, "_directory", lambda *a, **kw: None)
    def plan(*args, **kwargs):
        assert (tmp_path / ".active").is_dir()
        raise ConvergenceRefused("untrusted pin")
    monkeypatch.setattr(cv, "plan", plan)
    with pytest.raises(ConvergenceRefused, match="untrusted pin"):
        cv.converge("grant", "gway-005", state_root=tmp_path)
    assert not (tmp_path / ".active").exists()


def test_orphaned_node_journal_blocks_idempotent_fast_path(monkeypatch, tmp_path):
    """A missing global lock must not make an existing node journal ignorable."""
    from gway_remote import watchtower_exec_convergence as cv
    tmp_path.chmod(0o700)
    (tmp_path / "gway-005").mkdir(mode=0o700)
    monkeypatch.setattr(cv.os, "geteuid", lambda: 0)
    monkeypatch.setattr(cv, "_directory", lambda *a, **kw: None)
    def reject(*args, **kwargs):
        raise AssertionError("must fail before checking plan or probing limits")
    monkeypatch.setattr(cv, "plan", reject)
    with pytest.raises(ConvergenceRefused, match="pending transaction"):
        cv.converge("grant", "gway-005", state_root=tmp_path, runner=reject)
    assert (tmp_path / ".active").is_dir()


def test_incomplete_preparation_leaves_no_unrecoverable_journal(monkeypatch, tmp_path):
    """Pre-mutation _claim failure is safe to clean; no live changes occurred."""
    from pathlib import Path
    from types import SimpleNamespace
    from gway_remote import watchtower_exec_convergence as cv
    from gway_remote import node_registry_inventory
    tmp_path.chmod(0o700)
    p = Path("/tmp/nonexistent-bootstrap-test")
    planned = (p, b"before", b"after", SimpleNamespace())
    monkeypatch.setattr(cv, "plan", lambda *a, **kw:
                        {"known": planned, "config": planned, "node": "gway-005"})
    monkeypatch.setattr(cv.os, "geteuid", lambda: 0)
    monkeypatch.setattr(cv, "_directory", lambda *a, **kw: None)
    monkeypatch.setattr(node_registry_inventory, "_grants", lambda *_: {})
    def fail_claim(plan_data, stage, *, prior_eligible):
        stage.mkdir(mode=0o700)
        (stage / "known.before").write_bytes(b"before")
        raise OSError("test-staged-write-failure")
    monkeypatch.setattr(cv, "_claim", fail_claim)
    def reject(*args, **kwargs):
        raise AssertionError("no live mutations allowed")
    with pytest.raises(OSError, match="test-staged-write-failure"):
        cv.converge("grant", "gway-005", state_root=tmp_path,
                    set_grant=reject, publisher=reject, runner=reject)
    assert not (tmp_path / "gway-005").exists()
    assert not (tmp_path / ".active").exists()


@pytest.mark.parametrize("node", ["../gway-005", "/tmp/fake", "gway-999/extra", ""])
def test_invalid_node_cannot_construct_transaction_paths(monkeypatch, tmp_path, node):
    from gway_remote import watchtower_exec_convergence as cv
    monkeypatch.setattr(cv.os, "geteuid", lambda: 0)
    with pytest.raises(ConvergenceRefused, match="invalid execution action"):
        cv.converge("grant", node, state_root=tmp_path)
    assert not (tmp_path / ".active").exists()
