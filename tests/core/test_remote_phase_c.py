"""Private API deployment contracts, discovered by unittest."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class RemotePhaseCContracts(unittest.TestCase):
    def test_wireguard_service_private_binding(self):
        unit = (ROOT / "deploy/systemd/user/gway-remote-mobile-api-wireguard.service").read_text()
        self.assertIn("--host 10.90.0.2 --port 8765", unit)
        self.assertNotIn("--host 0.0.0.0", unit)
        self.assertIn("EnvironmentFile=%h/.config/gway-remote/mobile-api.env", unit)

    def test_gateway_explicit_paths_only(self):
        conf = (ROOT / "deploy/nginx/gway-remote-locations.conf").read_text()
        for route in ("health", "commands", "execute"):
            with self.subTest(route=route):
                self.assertIn(f"location = /api/v1/{route}", conf)
                self.assertIn(f"location = /api/v1/nodes/gway-001/{route}", conf)
        self.assertNotIn("location /", conf)
        self.assertIn("proxy_pass http://10.90.0.2:8765", conf)
        self.assertIn("limit_except POST", conf)
        self.assertIn("proxy_set_header Authorization $http_authorization;", conf)

    def test_staging_scripts_do_not_reload_or_open_public_ports(self):
        for script in ("scripts/install-mobile-api-wireguard.sh", "scripts/stage-https-gateway.sh"):
            with self.subTest(script=script):
                text = (ROOT / script).read_text()
                self.assertNotIn("ufw allow", text)
                self.assertNotIn("iptables -A", text)
                self.assertNotIn("systemctl reload nginx\\n", text)
