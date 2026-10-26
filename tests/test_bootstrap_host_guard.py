"""Ensure served bootstrap refuses Watchtower and wrong host before mutation."""
import pathlib
import unittest


class BootstrapHostGuardTests(unittest.TestCase):
    def test_guard_precedes_package_install_and_download(self):
        source = (pathlib.Path(__file__).resolve().parents[1]
                  / "gway_remote" / "watchtower_enrollment.py").read_text()
        script = source.split('source = f"""#!/bin/sh', 1)[1].split('"""', 1)[0]
        watchtower = script.index("refusing satellite bootstrap on Watchtower")
        hostname = script.index("satellite bootstrap target hostname mismatch")
        install = script.index("apt-get update")
        download = script.index("curl -fsS")
        self.assertLess(watchtower, install)
        self.assertLess(hostname, install)
        self.assertLess(hostname, download)
        self.assertIn("/etc/gway-remote/watchtower.json", script)
        self.assertIn('hostname -s', script)
        self.assertIn("'{device}'", script)


if __name__ == "__main__":
    unittest.main()
