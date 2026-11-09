from datetime import datetime, timezone, timedelta
import pytest
from gway_remote.fleet_contract import project

NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)
INV = {"source": "watchtower-enrollment-ledger", "nodes": [
    {"node": "gway-001", "identity_verified": True, "reachable": "unknown"}]}


def test_missing_observations_are_unknown():
    row = project(INV, now=NOW)["nodes"][0]
    assert row["hardware"]["available"] is False
    assert row["services"]["available"] is False
    assert row["deployments"]["components"] == []


def test_rejects_untrusted_or_duplicate_inventory():
    with pytest.raises(ValueError):
        project({"source": "other", "nodes": []}, now=NOW)
    with pytest.raises(ValueError):
        project({**INV, "nodes": INV["nodes"] * 2}, now=NOW)


def test_stale_observations_fail_closed():
    old = (NOW - timedelta(minutes=6)).isoformat()
    result = project(INV, {"gway-001": {"hardware": {
        "schema": "gway-remote/hardware/v1", "checked_at": old,
        "host": {"cpu_temperature_c": 50}}}}, now=NOW)
    assert result["nodes"][0]["hardware"]["available"] is False


def test_fresh_observation_preserves_provenance():
    result = project(INV, {"gway-001": {"hardware": {
        "schema": "gway-remote/hardware/v1", "checked_at": NOW.isoformat(),
        "host": {"cpu_temperature_c": 52}}}}, now=NOW)
    assert result["nodes"][0]["hardware"]["data"]["cpu_temperature_c"] == 52
