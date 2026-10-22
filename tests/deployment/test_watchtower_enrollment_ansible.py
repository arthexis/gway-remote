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
        self.assertIn("location = /v1/enroll", route)
        self.assertNotIn("/invite", route)
        self.assertNotIn("/revoke", route)

    def test_log_format_excludes_uri_and_query(self):
        logging = Path("ansible/roles/watchtower_enrollment/files/gway-remote-watchtower-log.conf").read_text()
        self.assertIn("gway_enrollment_safe", logging)
        self.assertNotIn("$request_uri", logging)
        self.assertNotIn("$request ", logging)


if __name__ == "__main__":
    unittest.main()
