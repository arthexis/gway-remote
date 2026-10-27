"""Operator-facing host pin command must reject unauthorized targets before network."""
import pytest
from gway_remote.host_identity import HostIdentityError, validate_attestation


def test_attestation_requires_exact_active_identity():
    with pytest.raises(HostIdentityError):
        validate_attestation(
            {"schema": 1, "node": "gway-004", "state": "rotating"},
            node="gway-004",
        )


def test_host_pin_help_is_available_without_watchtower(capsys, monkeypatch):
    from gway_remote.__main__ import main
    import sys
    monkeypatch.setattr(sys, 'argv', ['gway-remote', 'inspection-host-pin', '--help'])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert "authorize-initial" in capsys.readouterr().out
