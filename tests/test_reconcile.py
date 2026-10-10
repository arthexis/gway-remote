from datetime import datetime, timedelta, timezone

import pytest

from gway_remote.reconcile import (
    Decision, TARGETS, TargetState, reconcile,
)

NOW = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
A, B, C = ("a" * 40, "b" * 40, "c" * 40)


def states(*, changed=("ocpp-csms",), age=20, ci="success"):
    return tuple(
        TargetState(name, B if name in changed else A, A,
                    NOW - timedelta(minutes=age), ci)
        for name, _ in TARGETS
    )


def test_up_to_date():
    assert reconcile(states(changed=(), age=0), NOW).decision == Decision.UP_TO_DATE


@pytest.mark.parametrize("age", [0, 5, 19.999])
def test_waiting(age):
    p = reconcile(states(age=age), NOW)
    assert p.decision == Decision.WAITING
    assert p.targets == ()


def test_boundary_and_order():
    p = reconcile(states(changed=("ocpp-csms", "gway-lcd-sound")), NOW)
    assert p.decision == Decision.READY
    assert [t.name for t in p.targets] == ["ocpp-csms", "gway-lcd-sound"]
    assert len(p.desired_revisions) == 3


def test_latest_change_any_repository_resets_deadline():
    s = list(states(age=30))
    s[1] = TargetState(s[1].name, A, A, NOW - timedelta(minutes=5), "success")
    p = reconcile(s, NOW)
    assert p.decision == Decision.WAITING
    assert p.quiet_until == NOW + timedelta(minutes=15)


@pytest.mark.parametrize("ci", ["failure", "pending", "unknown", ""])
def test_ci_fail_closed(ci):
    assert reconcile(states(ci=ci), NOW).decision == Decision.BLOCKED


def test_unchanged_target_ci_does_not_block():
    s = list(states())
    s[1] = TargetState(s[1].name, A, A, s[1].main_updated_at, "failure")
    assert reconcile(s, NOW).decision == Decision.READY


def test_missing_timestamp_and_unknown_deployment():
    s = list(states())
    s[0] = TargetState(s[0].name, B, A, None, "success")
    assert reconcile(s, NOW).decision == Decision.BLOCKED
    s[0] = TargetState(s[0].name, B, None, NOW, "success")
    assert reconcile(s, NOW).decision == Decision.BLOCKED


def test_invalid_sha():
    s = list(states())
    s[0] = TargetState(s[0].name, "short", A, NOW, "success")
    assert reconcile(s, NOW).decision == Decision.BLOCKED


def test_missing_duplicate_extra_target():
    s = states()
    assert reconcile(s[:-1], NOW).decision == Decision.BLOCKED
    assert reconcile(s + (s[0],), NOW).decision == Decision.BLOCKED


def test_timezone_and_determinism():
    tz = timezone(timedelta(hours=-6))
    s = tuple(TargetState(t.name, t.desired_sha, t.deployed_sha,
                          t.main_updated_at.astimezone(tz), t.ci_status)
              for t in states())
    assert reconcile(s, NOW) == reconcile(s, NOW)
    assert reconcile(s, NOW).decision == Decision.READY


def test_naive_and_future_timestamps():
    s = list(states())
    s[0] = TargetState(s[0].name, B, A, NOW.replace(tzinfo=None), "success")
    assert reconcile(s, NOW).decision == Decision.BLOCKED
    s[0] = TargetState(s[0].name, B, A, NOW + timedelta(minutes=1), "success")
    assert reconcile(s, NOW).decision == Decision.BLOCKED
    with pytest.raises(ValueError):
        reconcile(states(), NOW.replace(tzinfo=None))
