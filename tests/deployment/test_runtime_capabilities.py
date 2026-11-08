"""Regression tests for conservative deployment evidence capabilities."""
import unittest
from unittest.mock import patch, SimpleNamespace

from gway_remote.status import kiosk_activation_evidence

from gway_remote.deployment_evidence import adapt_component, validate


SHA = "a" * 40
OBSERVED = "2026-11-08T20:30:00+00:00"


def record(name, **overrides):
    return {"name": name, "installed_sha": SHA, "health": "healthy",
            "evidence": None, **overrides}


class RuntimeCapabilitiesTests(unittest.TestCase):

    def test_agentops_cli_has_no_required_daemon(self):
        result = validate(adapt_component(record("gway-agent-ops"), observed_at=OBSERVED))
        assert result["installation_state"] == "activated"
        assert result["runtime_state"] == "not_applicable"
        assert result["capabilities"]["runtime_required"] is False
        assert result["capabilities"]["runtime_probe"] is False

    def test_agentops_without_verified_activation_remains_unknown(self):
        result = validate(adapt_component(
            {"name": "gway-agent-ops", "installed_sha": None, "health": "healthy"},
            observed_at=OBSERVED))
        assert result["installation_state"] == "unknown"
        assert result["runtime_state"] == "unknown"

    def test_reports_executable_still_requires_runtime_readiness(self):
        result = validate(adapt_component(record("ocpp-reports"), observed_at=OBSERVED))
        assert result["runtime_state"] == "healthy"
        assert result["capabilities"]["runtime_required"] is True

    def test_kiosk_revision_file_does_not_claim_activation(self):
        result = validate(adapt_component(record("gway-ap-kiosk"), observed_at=OBSERVED))
        assert result["installation_state"] == "unknown"
        assert result["activated_revision"] is None
        assert result["runtime_state"] == "healthy"

    def test_kiosk_verified_evidence_activates_without_changing_health(self):
        result = validate(adapt_component(
            record("gway-ap-kiosk", health="unhealthy"), observed_at=OBSERVED,
            kiosk_activation_verified=True))
        assert result["installation_state"] == "activated"
        assert result["activated_revision"] == SHA
        assert result["runtime_state"] == "unhealthy"

    def test_kiosk_missing_contradictory_or_quick_stays_unknown(self):
        for verified, revision, depth in (
            (False, SHA, "deep"), (True, None, "deep"),
            (True, "invalid", "deep"), (True, SHA, "quick"),
        ):
            result = adapt_component(
                record("gway-ap-kiosk", installed_sha=revision),
                observed_at=OBSERVED, depth=depth,
                kiosk_activation_verified=verified)
            assert result["installation_state"] == "unknown"
            assert result["activated_revision"] is None

    def test_checker_strict_json_exit_code_and_sha(self):
        cases = [
            (0, '{"activation_verified": true}', True),
            (0, '{"activation_verified": false}', False),
            (0, '{"activation_verified": true, "extra": 1}', False),
            (0, '{"activation_verified": 1}', False),
            (0, 'invalid', False),
            (1, '{"activation_verified": true}', False),
        ]
        for code, output, expected in cases:
            with patch("gway_remote.status.subprocess.run",
                       return_value=SimpleNamespace(returncode=code, stdout=output)) as run, \
                 patch("gway_remote.status.installed_revision", return_value=SHA):
                assert kiosk_activation_evidence(SHA) is expected
                assert run.call_args.kwargs["timeout"] == 3
                assert run.call_args.args[0] == ["/usr/local/libexec/gway-kiosk-verify-activation"]
        with patch("gway_remote.status.subprocess.run") as run:
            assert kiosk_activation_evidence("bad-sha") is False
            run.assert_not_called()
        with patch("gway_remote.status.subprocess.run",
                   return_value=SimpleNamespace(returncode=0, stdout='{"activation_verified": true}')), \
             patch("gway_remote.status.installed_revision", return_value="b" * 40):
            assert kiosk_activation_evidence(SHA) is False

    def test_unknown_component_never_infers_not_applicable(self):
        result = validate(adapt_component(record("ocpp-simulator"), observed_at=OBSERVED))
        assert result["runtime_state"] == "healthy"
        assert result["capabilities"]["runtime_required"] is True

    def test_quick_observation_does_not_infer_cli_activation_health(self):
        result = validate(adapt_component(
            record("gway-agent-ops"), observed_at=OBSERVED, depth="quick"))
        assert result["runtime_state"] == "not_applicable"
        assert result["observed_at"] is None
