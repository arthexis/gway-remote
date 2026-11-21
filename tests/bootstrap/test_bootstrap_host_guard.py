"""Shell bootstrap host-guard checks against the actual rendered artifact."""
import subprocess
import unittest

from gway_remote.bootstrap_script import render_bootstrap_script

# Explicit benign reviewed metadata for hermetic shell parsing only.
RELEASE = dict(release_revision="a" * 40,
               client_sha256="b" * 64,
               relay_public_key="ssh-ed25519 " + "A" * 43 + "=")


class BootstrapHostGuardTests(unittest.TestCase):
    def test_guard_precedes_package_install_and_download(self):
        script = render_bootstrap_script("a" * 40, "gway-004", "b" * 44, **RELEASE).decode("utf-8")
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

    def test_full_bootstrap_requires_verified_release_and_receipt(self):
        script = render_bootstrap_script("a" * 40, "gway-004", "b" * 44, **RELEASE).decode()
        assert "git -C \"$temp/source\" rev-parse HEAD" in script
        assert "ansible/bootstrap-node.yml" in script
        assert "sha256sum -c" in script
        assert script.index("sha256sum -c") < script.index("python3 \"$temp/client.py\" bootstrap")
        assert script.index("ansible-playbook") < script.index("/complete")
        assert "REMOTE_EXECUTION_UNVERIFIED" in script
        assert "local_ready_verified" in script
        assert "LOCAL_BOOTSTRAP_READY" not in script

    def test_missing_release_metadata_is_fail_closed(self):
        with self.assertRaises(ValueError):
            render_bootstrap_script("a" * 40, "gway-004", "b" * 44,
                                    release_revision="main", **{
                                        "relay_public_key": RELEASE["relay_public_key"],
                                        "client_sha256": RELEASE["client_sha256"]})

    def test_named_satellite_keeps_original_wireguard_only_contract(self):
        script = render_bootstrap_script("a" * 40, "ocpp-abb-1", "b" * 44).decode()
        self.assertIn("apt-get install -y -qq python3 curl wireguard-tools", script)
        self.assertNotIn("ansible-playbook", script)
        self.assertNotIn("bootstrap-node.yml", script)
        self.assertNotIn("local_setup_reported", script)
        self.assertIn("/complete", script)

    def test_shell_artifacts_have_valid_syntax_without_execution(self):
        for repair in (False, True):
            with self.subTest(repair=repair):
                script = render_bootstrap_script("a" * 40, "gway-004", "b" * 44,
                                                 repair_host_identity=repair, **RELEASE)
                result = subprocess.run(["sh", "-n"], input=script, capture_output=True,
                                        timeout=3, check=False)
                self.assertEqual(result.returncode, 0, result.stderr.decode())


if __name__ == "__main__":
    unittest.main()
