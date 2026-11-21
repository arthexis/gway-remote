"""Hermetic canary signature rotation policy tests; never invoke a real device."""
import tempfile
from pathlib import Path
from subprocess import CompletedProcess
import unittest
from unittest.mock import patch

from gway_remote.android_canary_install import InstallBlocked, install


class FakeAdb:
    def __init__(self, *, conflict=True, unknown=False, installed=True, second_fails=False):
        self.conflict = conflict
        self.unknown = unknown
        self.installed = installed
        self.second_fails = second_fails
        self.production = "package:/data/app/production/base.apk"
        self.calls = []
        self.attempts = 0
        self.uninstalled = []

    def __call__(self, argv, timeout=40):
        self.calls.append(argv)
        args = argv[3:] if len(argv) >= 3 and argv[1] == "-s" else argv[1:]
        if args == ["devices", "-l"]:
            return CompletedProcess(argv, 0, "List of devices attached\nDEVICE device usb:1-1 product:phone\n", "")
        if args == ["shell", "getprop", "ro.kernel.qemu"]:
            return CompletedProcess(argv, 0, "0\n", "")
        if args[:3] == ["shell", "pm", "path"]:
            package = args[3]
            value = self.production if package == "com.arthexis.gwayremote" else (
                "package:/data/app/canary/base.apk" if self.installed else "")
            # Real Android can return status 1 for an absent package.
            return CompletedProcess(argv, 0 if value else 1, value + "\n", "")
        if args[:4] == ["shell", "pm", "list", "packages"]:
            return CompletedProcess(argv, 0,
                "package:com.arthexis.gwayremote.canary\n" if self.installed else "", "")
        if args[:2] == ["install", "-r"]:
            self.attempts += 1
            if self.conflict and self.attempts == 1:
                reason = "INSTALL_FAILED_UNKNOWN" if self.unknown else "INSTALL_FAILED_UPDATE_INCOMPATIBLE"
                return CompletedProcess(argv, 1, "", "Failure [" + reason + "]")
            if self.second_fails:
                return CompletedProcess(argv, 1, "", "Failure")
            self.installed = True
            return CompletedProcess(argv, 0, "Success\n", "")
        if args[:1] == ["uninstall"]:
            self.uninstalled.append(args[1])
            self.installed = False
            return CompletedProcess(argv, 0, "Success\n", "")
        raise AssertionError("unexpected adb operation: " + repr(argv))


class AndroidCanaryInstallPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.apk = Path(self.tmp.name) / "verified-canary.apk"
        self.apk.write_bytes(b"A" * 11000)

    def tearDown(self):
        self.tmp.cleanup()

    def test_normal_upgrade_preserves_canary_data(self):
        fake = FakeAdb(conflict=False)
        self.assertEqual(install(str(self.apk), call=fake), "updated")
        self.assertEqual(fake.uninstalled, [])

    def test_streamed_install_banner_is_a_success_without_reset(self):
        fake = FakeAdb(conflict=False)
        original = fake.__call__
        def streamed(argv, timeout=40):
            result = original(argv, timeout)
            if argv[-3:-1] == ["install", "-r"] and result.returncode == 0:
                return CompletedProcess(argv, 0, "Performing Streamed Install\\nSuccess\\n", "")
            return result
        self.assertEqual(install(str(self.apk), call=streamed), "updated")
        self.assertEqual(fake.uninstalled, [])

    def test_streamed_install_after_signature_reset_is_accepted(self):
        fake = FakeAdb()
        original = fake.__call__
        def streamed(argv, timeout=40):
            result = original(argv, timeout)
            if argv[-3:-1] == ["install", "-r"] and result.returncode == 0:
                return CompletedProcess(argv, 0, "Performing Streamed Install\\nSuccess\\n", "")
            return result
        self.assertEqual(install(str(self.apk), call=streamed, reset_allowed=True),
                         "canary_reset_and_installed")
        self.assertEqual(fake.uninstalled, ["com.arthexis.gwayremote.canary"])

    def test_unknown_zero_exit_output_never_triggers_reset(self):
        fake = FakeAdb(conflict=False)
        original = fake.__call__
        def ambiguous(argv, timeout=40):
            result = original(argv, timeout)
            if argv[-3:-1] == ["install", "-r"]:
                return CompletedProcess(argv, 0, "Performing Streamed Install\\n", "")
            return result
        with self.assertRaisesRegex(InstallBlocked, "success_unconfirmed"):
            install(str(self.apk), call=ambiguous, reset_allowed=True)
        self.assertEqual(fake.uninstalled, [])

    def test_signature_conflict_fails_closed_by_default(self):
        fake = FakeAdb()
        with self.assertRaisesRegex(InstallBlocked, "no_reset"):
            install(str(self.apk), call=fake)
        self.assertEqual(fake.uninstalled, [])

    def test_explicit_conflict_reset_uninstalls_only_canary(self):
        fake = FakeAdb()
        self.assertEqual(install(str(self.apk), reset_allowed=True, call=fake),
                         "canary_reset_and_installed")
        self.assertEqual(fake.uninstalled, ["com.arthexis.gwayremote.canary"])
        self.assertEqual(fake.attempts, 2)

    def test_unexpected_install_error_never_resets(self):
        fake = FakeAdb(unknown=True)
        with self.assertRaises(InstallBlocked):
            install(str(self.apk), reset_allowed=True, call=fake)
        self.assertEqual(fake.uninstalled, [])

    def test_second_install_failure_is_not_retried_or_widened(self):
        fake = FakeAdb(second_fails=True)
        with self.assertRaisesRegex(InstallBlocked, "reinstall_failed"):
            install(str(self.apk), reset_allowed=True, call=fake)
        self.assertEqual(fake.attempts, 2)
        self.assertEqual(fake.uninstalled, ["com.arthexis.gwayremote.canary"])

    def test_package_listing_must_confirm_absence_after_uninstall(self):
        fake = FakeAdb()
        original = fake.__call__
        def stale_listing(argv, timeout=40):
            if argv[-5:] == ["shell", "pm", "list", "packages",
                             "com.arthexis.gwayremote.canary"]:
                return CompletedProcess(argv, 0,
                    "package:com.arthexis.gwayremote.canary", "")
            return original(argv, timeout)
        with self.assertRaisesRegex(InstallBlocked, "reset_not_confirmed"):
            install(str(self.apk), reset_allowed=True, call=stale_listing)
        self.assertEqual(fake.uninstalled, ["com.arthexis.gwayremote.canary"])
        self.assertEqual(fake.attempts, 1)

    def test_missing_canary_is_never_uninstalled(self):
        fake = FakeAdb(installed=False)
        with self.assertRaisesRegex(InstallBlocked, "not_installed"):
            install(str(self.apk), reset_allowed=True, call=fake)
        self.assertEqual(fake.uninstalled, [])

    def test_production_path_drift_is_detected(self):
        fake = FakeAdb(conflict=False)
        original = fake.__call__
        def changed(argv, timeout=40):
            if argv[-4:] == ["shell", "pm", "path", "com.arthexis.gwayremote"]:
                seen = sum(1 for x in fake.calls if x[-4:] == argv[-4:])
                if seen:
                    fake.production = "package:/data/app/changed/base.apk"
            return original(argv, timeout)
        with self.assertRaisesRegex(InstallBlocked, "production_path_changed"):
            install(str(self.apk), call=changed)

    def test_invalid_apk_is_rejected_before_usb(self):
        with self.assertRaisesRegex(InstallBlocked, "invalid_verified_apk_path"):
            install(str(self.apk) + "-missing", call=FakeAdb())


if __name__ == "__main__":
    unittest.main()
