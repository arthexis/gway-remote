"""Shared offline enrollment fixtures for the explicit bootstrap pytest suite."""

import pytest

from gway_remote.watchtower_enrollment import Ledger


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "enrollment.sqlite3", network="10.90.0.0/24",
                  gateway="10.90.0.1")
