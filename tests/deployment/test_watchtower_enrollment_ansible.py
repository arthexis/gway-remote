import unittest
from pathlib import Path


class WatchtowerEnrollmentAnsibleTests(unittest.TestCase):
    def test_staging_role_is_explicit_and_has_no_public_admin_route(self):
        tasks = Path("ansible/roles/watchtower_enrollment/tasks/main.yml").read_text()
        unit = Path("ansible/roles/watchtower_enrollment/templates/gway-remote-watchtower-enroll.service.j2").read_text()
        route = Path("ansible/roles/watchtower_enrollment/files/register.gelectriic.com.enrollment.conf").read_text()
        self.assertIn("watchtower_enrollment_apply | bool", tasks)
        self.assertIn("must not target gway-001", tasks)
        self.assertIn("--host 127.0.0.1", unit)
        self.assertIn("watchtower serve", unit)
        self.assertIn("--read-only-stage", unit)
        self.assertIn("DynamicUser=yes", unit)
        self.assertNotIn("wg set", unit)
        self.assertIn("location = /v1/enroll", route)
        self.assertNotIn("/invite", route)
        self.assertNotIn("/revoke", route)

    def test_log_format_excludes_uri_and_query(self):
        logging = Path("ansible/roles/watchtower_enrollment/files/gway-remote-watchtower-log.conf").read_text()
        self.assertIn("gway_enrollment_safe", logging)
        self.assertNotIn("$request_uri", logging)
        self.assertNotIn("$request ", logging)

    def test_production_owner_is_explicit_and_inert_by_default(self):
        defaults = Path("ansible/roles/watchtower_enrollment_production/defaults/main.yml").read_text()
        tasks = Path("ansible/roles/watchtower_enrollment_production/tasks/main.yml").read_text()
        unit = Path("ansible/roles/watchtower_enrollment_production/templates/gway-remote-watchtower-enroll-production.service.j2").read_text()
        runbook = Path("docs/watchtower-production-cutover.md").read_text()
        self.assertIn("watchtower_enrollment_production_apply: false", defaults)
        self.assertIn("watchtower_enrollment_production_activate: false", defaults)
        self.assertIn("watchtower_enrollment_production_network | length > 0", tasks)
        self.assertIn("watchtower_enrollment_production_gateway | length > 0", tasks)
        self.assertIn("must not target gway-001", tasks)
        self.assertIn("ansible.builtin.systemd:", tasks)
        self.assertNotIn("ansible.builtin.systemd_service:", tasks)
        self.assertIn("--host 127.0.0.1", unit)
        self.assertIn("User=root", unit)
        self.assertIn("ReadWritePaths=/etc/wireguard", unit)
        self.assertIn("CapabilityBoundingSet=CAP_NET_ADMIN", unit)
        self.assertNotIn("--read-only-stage", unit)
        self.assertIn("Keep the legacy service running", runbook)
        self.assertIn("Do not restart", runbook)

    def test_production_role_stages_token_safe_nginx_contract(self):
        tasks = Path("ansible/roles/watchtower_enrollment_production/tasks/main.yml").read_text()
        logging = Path("ansible/roles/watchtower_enrollment_production/files/gway-remote-watchtower-log.conf").read_text()
        route = Path("ansible/roles/watchtower_enrollment_production/files/register.gelectriic.com.enrollment.conf").read_text()
        self.assertIn("/etc/nginx/conf.d/gway-remote-watchtower-log.conf", tasks)
        self.assertIn("nginx -t", tasks)
        self.assertIn("gway_enrollment_safe", logging)
        self.assertNotIn("$request_uri", logging)
        self.assertNotIn("$request ", logging)
        self.assertIn("location = /v1/enroll", route)
        self.assertIn("access_log", route)
        self.assertIn("gway_enrollment_safe", route)


if __name__ == "__main__":
    unittest.main()
