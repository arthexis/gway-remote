"""Hermetic fleet status transitions, destination and safe SSH evidence."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from gway_remote import fleet_lcd_notifications as fleet

NOW = datetime(2026, 11, 24, 7, 0, tzinfo=timezone.utc)


def test_probes_are_fixed_and_ssh_host_pinned():
    seen = []
    def run(args, **kwargs):
        seen.append(args)
        return SimpleNamespace(returncode=0)
    assert fleet.probe("ocpp-abb-1", "ocpp-reports-ingest.service", run=run) == "healthy"
    assert seen[0][0] == "ssh"
    assert "StrictHostKeyChecking=yes" in seen[0]
    assert seen[0][-4:] == ["ubuntu@ocpp-abb-1", "/usr/bin/systemctl",
                           "is-active", "--quiet", "ocpp-reports-ingest.service"][-4:]
    with pytest.raises(ValueError):
        fleet.probe("unknown-node", "sshd.service", run=run)
    with pytest.raises(ValueError):
        fleet.probe("ocpp-abb-1", "bash -c evil", run=run)


@pytest.mark.parametrize("code,state", [(0,"healthy"),(3,"down"),(255,"unreachable"),(4,"degraded")])
def test_ssh_and_service_failures_are_not_conflated(code,state):
    assert fleet.probe("gelectriic.com", "nginx.service",
                       run=lambda *a,**kw: SimpleNamespace(returncode=code)) == state


def test_two_bad_and_two_good_samples_with_persistent_incident_identity():
    a, event = fleet.update(None, "healthy", NOW)
    assert event is None and a["active"] is None
    a, event = fleet.update(a, "down", NOW)
    assert event is None
    a, event = fleet.update(a, "down", NOW+timedelta(minutes=1))
    assert event == "down" and a["active"] == "down"
    episode = a["episode"]
    a, event = fleet.update(a, "down", NOW+timedelta(minutes=2))
    assert event is None and a["episode"] == episode
    a, event = fleet.update(a, "healthy", NOW+timedelta(minutes=3))
    assert event is None and a["active"] == "down"
    a, event = fleet.update(a, "healthy", NOW+timedelta(minutes=4))
    assert event == "recovered" and a["active"] is None and a["episode"] == episode


def test_degraded_probe_is_not_a_confirmed_service_down():
    first, _ = fleet.update(None,"unreachable",NOW)
    second, event = fleet.update(first,"unreachable",NOW+timedelta(minutes=1))
    assert event == "unreachable"
    doc = fleet.event_document("ocpp-abb-1","ocpp-reports-ingest.service",
                               event,second["episode"])
    assert doc["target_node"] == "ocpp-abb-1"
    assert doc["origin_node"] == "gway-001"
    assert doc["state"] == "unreachable"
    assert doc["reason_code"] == "NODE_UNREACHABLE"
    assert doc["severity"] == "error"


def test_complete_monitor_cycle_does_not_sound_on_poll_or_startup(monkeypatch,tmp_path):
    monkeypatch.setattr(fleet.socket,"gethostname",lambda:"gway-001")
    state = tmp_path / "fleet.json"
    fake = {("ocpp-abb-1","ocpp-reports-ingest.service"): "down"}
    observed = []
    def probe(node,service):
        return fake.get((node,service),"healthy")
    def sender(document, *, sound):
        observed.append((document,sound))
    fleet.cycle(state=state,now=NOW,monitor=probe,sender=sender)
    assert observed == []  # cold baseline: one bad reading cannot alarm
    fleet.cycle(state=state,now=NOW+timedelta(minutes=1),monitor=probe,sender=sender)
    assert len(observed)==1 and observed[0][1]=="critical"
    assert observed[0][0]["subject"]["name"]=="ocpp-reports-ingest.service"
    fleet.cycle(state=state,now=NOW+timedelta(minutes=2),monitor=probe,sender=sender)
    assert len(observed)==2 and observed[-1][1] is None
    fake.clear()
    fleet.cycle(state=state,now=NOW+timedelta(minutes=3),monitor=probe,sender=sender)
    fleet.cycle(state=state,now=NOW+timedelta(minutes=4),monitor=probe,sender=sender)
    assert observed[-1][0]["state"] == "recovered"
    assert observed[-1][1] == "ok"
    assert state.stat().st_mode & 0o077 == 0


def test_monitor_refuses_unapproved_host(monkeypatch,tmp_path):
    monkeypatch.setattr(fleet.socket,"gethostname",lambda:"laptop")
    with pytest.raises(PermissionError):
        fleet.cycle(state=tmp_path/"state",monitor=lambda *args:"healthy")
