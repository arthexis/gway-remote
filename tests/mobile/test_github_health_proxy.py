"""Static Nginx and Android contracts for GitHub Health forwarding."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class GitHubHealthProxyTests(unittest.TestCase):
    def test_both_public_paths_forward_to_existing_private_route(self):
        config = (ROOT / "deploy/nginx/gway-remote-locations.conf").read_text()
        for route in ("/api/v1/github-health", "/api/v1/nodes/gway-001/github-health"):
            block = config.split("location = " + route + " {", 1)[1].split("}", 1)[0]
            self.assertIn("limit_except GET", block)
            self.assertIn("proxy_pass http://10.90.0.2:8765/api/v1/github-health;", block)
            self.assertIn("proxy_set_header Authorization $http_authorization;", block)

    def test_android_uses_the_proxied_api_route(self):
        client = (ROOT / "android/app/src/main/java/com/arthexis/gwayremote/GitHubHealthPanel.kt").read_text()
        self.assertIn('request("/api/v1/github-health")', client)


if __name__ == "__main__":
    unittest.main()
