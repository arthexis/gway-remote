"""Controller deployment status is verified, not inferred from attempts."""
import hashlib
import json
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from gway_remote.controller_release import controller_evidence
from gway_remote.mobile_deployments import overview


def fixture(tmp_path):
    executable = tmp_path / "gway-remote"
    executable.write_bytes(b"installed executable")
    executable.chmod(0o755)
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    receipt = tmp_path / "controller-deployment.json"
    record = {"schema": 1, "source_sha": "a" * 40,
              "executable_sha256": digest,
              "verified_at": "2026-01-01T00:00:00+00:00"}
    receipt.write_text(json.dumps(record))
    receipt.chmod(0o644)
    def read(running=digest):
        return controller_evidence(receipt=receipt, executable=executable,
                                   running_digest=running, uid=os.getuid())
    return executable, receipt, record, read


def test_verified_fields_and_mobile_contract(tmp_path):
    _, _, record, read = fixture(tmp_path)
    with patch("gway_remote.mobile_deployments.export_targets", return_value={"targets": []}):
        value = overview({}, attempts_reader=lambda: {}, revision_reader=lambda _: None,
                         controller_reader=read)
    assert value["controller"] == {"name": "gway-remote", "installed_sha": "a" * 40,
        "last_successful_update": record["verified_at"], "evidence": "verified"}
    assert value["schema"] == 1
    assert value["dispatch_enabled"] is False


def test_missing_corrupt_and_untrusted_evidence(tmp_path):
    executable, receipt, record, read = fixture(tmp_path)
    receipt.unlink()
    assert read()["evidence"] == "unavailable"
    receipt.write_text("{")
    assert read()["evidence"] == "unavailable"
    receipt.write_text(json.dumps(record))
    receipt.chmod(0o666)
    assert read()["evidence"] == "unavailable"
    receipt.chmod(0o644)
    other = tmp_path / "other"
    receipt.rename(other)
    receipt.symlink_to(other)
    assert read()["evidence"] == "unavailable"


def test_stale_running_or_installed_archive(tmp_path):
    executable, _, _, read = fixture(tmp_path)
    assert read(None)["evidence"] == "unavailable"
    assert read("b" * 64)["evidence"] == "unavailable"
    executable.write_bytes(b"replacement executable")
    assert read()["installed_sha"] is None
    assert read()["last_successful_update"] is None


def test_invalid_revision_and_timestamps(tmp_path):
    _, receipt, record, read = fixture(tmp_path)
    for field, value in (("source_sha", "latest"), ("schema", True),
                         ("verified_at", "2026-01-01T00:00:00"),
                         ("verified_at", (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()),
                         ("executable_sha256", "b" * 64)):
        receipt.write_text(json.dumps({**record, field: value}))
        assert read()["evidence"] == "unavailable"
