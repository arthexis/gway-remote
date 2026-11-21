"""Pure bootstrap release provenance checks, without host access."""
from pathlib import Path
from unittest.mock import patch
import pytest

from gway_remote import bootstrap_release as release


def test_release_marker_requires_root_and_exact_sha(tmp_path):
    p = tmp_path / "revision"
    p.write_text("a" * 40 + "\n")
    with patch.object(release.os, "geteuid", return_value=1001):
        with pytest.raises(release.ReleaseUnavailable):
            release._root_owned_revision(p)
    p.write_text("main\n")
    with patch.object(release.os, "geteuid", return_value=0):
        with pytest.raises(release.ReleaseUnavailable):
            release._root_owned_revision(p)
    assert release.SHA.fullmatch("f" * 40)
    assert not release.SHA.fullmatch("refs/heads/main")


def test_missing_release_marker_is_never_inferred_from_git_head(tmp_path):
    with patch.object(release.os, "geteuid", return_value=0):
        with pytest.raises(OSError):
            release._root_owned_revision(tmp_path / "missing")
    source = (Path(__file__).resolve().parents[2] /
              "ansible/playbooks/watchtower-enrollment-refresh.yml").read_text()
    assert "bootstrap-release.sha" in source
