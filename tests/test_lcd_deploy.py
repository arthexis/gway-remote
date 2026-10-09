"""LCD deployment task allowlist and non-destructive command sequencing."""
import unittest
from unittest.mock import patch, call

from gway_remote.__main__ import validate, run


class LcdDeployTests(unittest.TestCase):
    SHA = "a" * 40

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

    def test_simulator_cannot_deploy_lcd(self):
        with self.assertRaises(ValueError):
            validate("ocpp-simulator", "arthexis/gway-lcd-sound", self.SHA)

    def test_dispatch_routes_to_explicit_deployer(self):
        with patch("gway_remote.__main__.deploy_lcd_sound") as deploy:
            run("lcd-sound-deploy", "arthexis/gway-lcd-sound", self.SHA)
            deploy.assert_called_once_with(self.SHA)

    def test_bad_repository_cannot_reach_deployer(self):
        with patch("gway_remote.__main__.deploy_lcd_sound") as deploy:
            with self.assertRaises(ValueError):
                run("lcd-sound-deploy", "arthexis/other", self.SHA)
            deploy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
