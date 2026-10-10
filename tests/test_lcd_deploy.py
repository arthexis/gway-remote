"""LCD deployment task allowlist and non-destructive command sequencing."""
import unittest
from unittest.mock import patch

from gway_remote.__main__ import validate, run, user_systemd_env


class LcdDeployTests(unittest.TestCase):
    SHA = "a" * 40

    def test_runner_uses_persistent_user_bus(self):
        with patch("gway_remote.__main__.os.getuid", return_value=1000), \
             patch("gway_remote.__main__.Path.is_socket", return_value=True), \
             patch.dict("gway_remote.__main__.os.environ", {"XDG_RUNTIME_DIR": ""}):
            env = user_systemd_env()
        self.assertEqual(env["XDG_RUNTIME_DIR"], "/run/user/1000")
        self.assertEqual(env["DBUS_SESSION_BUS_ADDRESS"], "unix:path=/run/user/1000/bus")

    def test_missing_user_bus_fails_explicitly(self):
        with patch("gway_remote.__main__.os.getuid", return_value=1000), \
             patch("gway_remote.__main__.Path.is_socket", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "User systemd bus unavailable"):
                user_systemd_env()

    def test_accepts_only_lcd_repository_and_sha(self):
        validate("lcd-sound-deploy", "arthexis/gway-lcd-sound", self.SHA)
        for repository, sha in [
            ("arthexis/ocpp-csms", self.SHA),
            ("arthexis/gway-lcd-sound", ""),
            ("arthexis/gway-lcd-sound", "main"),
            ("arthexis/gway-lcd-sound", "z" * 40),
        ]:
            with self.subTest(repository=repository, sha=sha):
                with self.assertRaises(ValueError):
                    validate("lcd-sound-deploy", repository, sha)

    def test_csms_deploy_restricted_to_main_repository(self):
        validate("ocpp-csms-deploy", "arthexis/ocpp-csms", self.SHA)
        with self.assertRaises(ValueError):
            validate("ocpp-csms-deploy", "arthexis/gway-lcd-sound", self.SHA)

    def test_csms_deploy_routes_to_explicit_deployer(self):
        with patch("gway_remote.__main__.deploy_csms") as deploy, patch("gway_remote.best_effort.manual_execute") as manual:
            run("ocpp-csms-deploy", "arthexis/ocpp-csms", self.SHA)
            manual.assert_called_once()

    def test_simulator_cannot_deploy_lcd(self):
        with self.assertRaises(ValueError):
            validate("ocpp-simulator", "arthexis/gway-lcd-sound", self.SHA)

    def test_dispatch_routes_to_explicit_deployer(self):
        with patch("gway_remote.__main__.deploy_lcd_sound") as deploy, patch("gway_remote.best_effort.manual_execute") as manual:
            run("lcd-sound-deploy", "arthexis/gway-lcd-sound", self.SHA)
            manual.assert_called_once()

    def test_bad_repository_cannot_reach_deployer(self):
        with patch("gway_remote.__main__.deploy_lcd_sound") as deploy:
            with self.assertRaises(ValueError):
                run("lcd-sound-deploy", "arthexis/other", self.SHA)
            deploy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
