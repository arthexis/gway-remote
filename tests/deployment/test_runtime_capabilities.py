"""Regression tests for conservative deployment evidence capabilities."""
from gway_remote.deployment_evidence import adapt_component, validate


SHA = "a" * 40
OBSERVED = "2026-11-08T20:30:00+00:00"


def record(name, **overrides):
    return {"name": name, "installed_sha": SHA, "health": "healthy",
            "evidence": None, **overrides}


def test_agentops_cli_has_no_required_daemon():
    result = validate(adapt_component(record("gway-agent-ops"), observed_at=OBSERVED))
    assert result["installation_state"] == "activated"
    assert result["runtime_state"] == "not_applicable"
    assert result["capabilities"]["runtime_required"] is False
    assert result["capabilities"]["runtime_probe"] is False


def test_agentops_without_verified_activation_remains_unknown():
    result = validate(adapt_component(
        {"name": "gway-agent-ops", "installed_sha": None, "health": "healthy"},
        observed_at=OBSERVED))
    assert result["installation_state"] == "unknown"
    assert result["runtime_state"] == "unknown"


def test_reports_executable_still_requires_runtime_readiness():
    result = validate(adapt_component(record("ocpp-reports"), observed_at=OBSERVED))
    assert result["runtime_state"] == "healthy"
    assert result["capabilities"]["runtime_required"] is True


def test_kiosk_revision_file_does_not_claim_activation():
    result = validate(adapt_component(record("gway-ap-kiosk"), observed_at=OBSERVED))
    assert result["installation_state"] == "unknown"
    assert result["activated_revision"] is None
    assert result["runtime_state"] == "healthy"


def test_unknown_component_never_infers_not_applicable():
    result = validate(adapt_component(record("ocpp-simulator"), observed_at=OBSERVED))
    assert result["runtime_state"] == "healthy"
    assert result["capabilities"]["runtime_required"] is True


def test_quick_observation_does_not_infer_cli_activation_health():
    result = validate(adapt_component(
        record("gway-agent-ops"), observed_at=OBSERVED, depth="quick"))
    assert result["runtime_state"] == "not_applicable"
    assert result["observed_at"] is None
