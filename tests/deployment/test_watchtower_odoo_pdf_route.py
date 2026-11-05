"""Guard bounded Watchtower PDF proxy activation and existing deployment boundary."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class OdooGatewayDeploymentTests(unittest.TestCase):
    def test_playbook_only_updates_existing_mobile_pdf_route(self):
        playbook = (ROOT / "ansible/playbooks/watchtower-odoo-pdf-route.yml").read_text()
        self.assertIn("/etc/nginx/snippets/gway-remote-locations.conf", playbook)
        self.assertIn("/etc/nginx/sites-enabled/remote.arthexis.com", playbook)
        self.assertIn('location ~ "^/api/v1/odoo/quotations/[1-9][0-9]{0,9}/pdf$"', playbook)
        self.assertIn("limit_except GET { deny all; }", playbook)
        self.assertIn("proxy_set_header Authorization $http_authorization;", playbook)
        self.assertIn("proxy_pass http://10.90.0.2:8765;", playbook)
        self.assertIn("blockinfile:", playbook)
        self.assertIn("create: false", playbook)
        self.assertIn("rescue:", playbook)
        self.assertIn("Restore the exact original proxy snippet", playbook)
        self.assertIn("argv: [nginx, -t]", playbook)
        self.assertNotIn("nginx -s stop", playbook)
        self.assertNotIn("listen 443", playbook)

    def test_only_existing_watchtower_deploy_path_runs_proxy_play(self):
        shell = (ROOT / "scripts/watchtower-auto-deploy.sh").read_text()
        self.assertIn('watchtower-odoo-pdf-route.yml', shell)
        self.assertIn('watchtower-mcp.yml', shell)
        self.assertIn('watchtower-enrollment-refresh.yml', shell)
        self.assertLess(shell.index('watchtower-mcp.yml'), shell.index('watchtower-odoo-pdf-route.yml'))
        self.assertIn('git -C "$tmp/source" checkout --quiet --detach "$sha"', shell)
