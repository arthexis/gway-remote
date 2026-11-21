"""Offline tests of the reviewed, one-URL installer identity/options builder."""
import importlib.util
from pathlib import Path
from unittest.mock import patch
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/build-bootstrap-vars.py"
_spec = importlib.util.spec_from_file_location("bootstrap_vars", SCRIPT)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)
REV = "a" * 40
KEY = "ssh-ed25519 " + "A" * 43 + "="


def build(installer, selected=None, override="", node="gway-007", revision=REV):
    def resolve(user, desired):
        if selected is not None:
            if desired and desired != selected:
                raise PermissionError("existing policy cannot migrate")
            return selected
        return desired or user
    return module.variables(node, revision, "/private/relay.pub", override,
                            public_key_reader=lambda _: KEY,
                            sudo_user_reader=lambda _: installer,
                            user_resolver=resolve)


def test_verified_installers_and_explicit_override():
    assert build("rth")["gway_bootstrap_installer"] == "rth"
    assert build("arthe", selected="arthe")["gway_bootstrap_installer"] == "arthe"
    assert build("rth", override="arthe")["gway_bootstrap_executor_override"] == "arthe"
    assert build(None, selected="rth")["gway_bootstrap_installer"] == "rth"


@pytest.mark.parametrize("installer,selected", [
    (None, None), (None, "gway-exec"), ("root", None), ("gway-relay", None)
])
def test_invalid_or_missing_installers_fail_closed(installer, selected):
    with pytest.raises((PermissionError, ValueError, TypeError)):
        build(installer, selected=selected)


def test_no_implicit_existing_account_migration():
    with pytest.raises(PermissionError):
        build("rth", selected="arthe", override="rth")


@pytest.mark.parametrize("node,revision", [
    ("gway-../../", REV), ("gway-7", REV), ("gway-007", "main"),
    ("gway-007", "a" * 39 + "z"),
])
def test_reject_unreviewed_node_or_revision(node, revision):
    with pytest.raises(ValueError):
        build("arthe", node=node, revision=revision)


def test_relay_file_is_checked_before_identity_and_sanitizes_errors():
    checked = []
    def bad_key(_):
        checked.append("read")
        raise PermissionError("unsafe symlink")
    def identity(_):
        checked.append("identity")
        return "arthe"
    with pytest.raises(PermissionError):
        module.variables("gway-007", REV, "/tmp/foo", public_key_reader=bad_key,
                         sudo_user_reader=identity)
    assert checked == ["read"]
