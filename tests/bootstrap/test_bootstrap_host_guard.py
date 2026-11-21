"""Shell bootstrap host-guard checks against the actual rendered artifact."""
import subprocess
import unittest

from gway_remote.bootstrap_script import render_bootstrap_script


class BootstrapHostGuardTests(unittest.TestCase):
    def test_guard_precedes_package_install_and_download(self):
        script = render_bootstrap_script("a" * 40, "gway-004", "b" * 44).decode("utf-8")
        watchtower = script.index("refusing satellite bootstrap on Watchtower")
        hostname = script.index("satellite bootstrap target hostname mismatch")
        install = script.index("apt-get update")
        download = script.index("curl -fsS")
        self.assertLess(watchtower, install)
        self.assertLess(hostname, install)
        self.assertLess(hostname, download)
        self.assertIn("/etc/gway-remote/watchtower.json", script)
        self.assertIn("hostname -s", script)
        self.assertIn("'gway-004'", script)

    def test_shell_artifacts_have_valid_syntax_without_execution(self):
        for repair in (False, True):
            with self.subTest(repair=repair):
                script = render_bootstrap_script("a" * 40, "gway-004", "b" * 44,
                                                 repair_host_identity=repair)
                result = subprocess.run(["sh", "-n"], input=script, capture_output=True,
                                        timeout=3, check=False)
                self.assertEqual(result.returncode, 0, result.stderr.decode())


if __name__ == "__main__":
    unittest.main()
