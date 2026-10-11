from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_wireguard_service_private_binding():
    unit = (ROOT / "deploy/systemd/user/gway-remote-mobile-api-wireguard.service").read_text()
    assert "--host 10.90.0.2 --port 8765" in unit
    assert "--host 0.0.0.0" not in unit
    assert "EnvironmentFile=%h/.config/gway-remote/mobile-api.env" in unit


def test_gateway_explicit_paths_only():
    conf = (ROOT / "deploy/nginx/gway-remote-locations.conf").read_text()
    for route in ("health", "commands", "execute"):
        assert f"location = /api/v1/{route}" in conf
        assert f"location = /api/v1/nodes/gway-001/{route}" in conf
    assert "location /" not in conf
    assert "proxy_pass http://10.90.0.2:8765" in conf
    assert "limit_except POST" in conf
    assert "proxy_set_header Authorization $http_authorization;" in conf


def test_staging_scripts_do_not_reload_or_open_public_ports():
    for script in ("scripts/install-mobile-api-wireguard.sh", "scripts/stage-https-gateway.sh"):
        text = (ROOT / script).read_text()
        assert "ufw allow" not in text
        assert "iptables -A" not in text
        assert "systemctl reload nginx\n" not in text
