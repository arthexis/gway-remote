"""Installed revision is independent of attempted journal SHA."""
import tempfile
from pathlib import Path
from unittest.mock import patch
from gway_remote.status import installed_revision


def test_installed_csms_release_is_read_from_symlink():
    with tempfile.TemporaryDirectory() as temp:
        home = Path(temp)
        version = home / ".local/share/ocpp-csms/releases" / ("a" * 12)
        version.mkdir(parents=True)
        (home / ".local/share/ocpp-csms/current").symlink_to(version)
        with patch("pathlib.Path.home", return_value=home):
            assert installed_revision("ocpp-csms") == "a" * 12
            assert installed_revision("ocpp-simulator") is None


def test_invalid_or_missing_link_is_unknown():
    with tempfile.TemporaryDirectory() as temp:
        home = Path(temp)
        location = home / ".local/share/ocpp-csms"
        location.mkdir(parents=True)
        (location / "current").symlink_to(location / "releases/missing")
        with patch("pathlib.Path.home", return_value=home):
            assert installed_revision("ocpp-csms") is None
