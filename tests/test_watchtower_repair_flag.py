"""Keep the public repair CLI spelling consistent across bootstrap entry points."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_repair_flag_is_short_and_does_not_conflict_with_replace():
    cli = (ROOT / "gway_remote/__main__.py").read_text()
    client = (ROOT / "gway_remote/wireguard_satellite.py").read_text()
    enrollment = (ROOT / "gway_remote/watchtower_enrollment.py").read_text()
    assert 'register_parser.add_argument("--repair", dest="repair_host_identity"' in cli
    assert 'watchtower_parser.add_argument("--repair", dest="repair_host_identity"' in cli
    assert 'boot.add_argument("--repair", dest="repair_host_identity"' in client
    assert '"--repair-host-identity"' not in cli + client + enrollment
    assert 'register_parser.add_argument("--replace"' in cli
    assert 'watchtower_parser.add_argument("--replace"' in cli
    assert " --repair' if repair_host_identity else ''" in enrollment
