"""Enforce stable alias and isolated known-hosts during attested first-pin."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from gway_remote.inspection_ssh_trust import validate_profile


def test_profile_rejects_alias_and_known_hosts_mismatch():
    lines = ("hostname 10.90.0.4\nbatchmode yes\nstricthostkeychecking true\n"
             "identitiesonly yes\nuser arthe\nproxyjump watchtower-inspection\n"
             "identityfile /tmp/identity\nuserknownhostsfile /tmp/inspection-known\n"
             "hostkeyalias wrong-alias\n")
    def run(*_args, **_kwargs):
        return SimpleNamespace(stdout=lines)
    with patch("gway_remote.inspection_ssh_trust.trusted_file"):
        with pytest.raises(ValueError, match="host key alias mismatch"):
            validate_profile("/tmp/ssh-config", "gway-004", hostname="10.90.0.4",
                             require_jump=True, host_key_alias="gway-inspection-gway-004",
                             expected_known_hosts="/tmp/inspection-known", runner=run)
        with pytest.raises(ValueError, match="known-hosts file mismatch"):
            validate_profile("/tmp/ssh-config", "gway-004", hostname="10.90.0.4",
                             require_jump=True, host_key_alias="wrong-alias",
                             expected_known_hosts="/tmp/different", runner=run)
        options = validate_profile("/tmp/ssh-config", "gway-004",
                                   hostname="10.90.0.4", require_jump=True,
                                   host_key_alias="wrong-alias",
                                   expected_known_hosts="/tmp/inspection-known", runner=run)
        assert options["hostkeyalias"] == "wrong-alias"
