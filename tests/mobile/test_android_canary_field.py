"""Hermetic guards for the Android canary field consumer (no real adb/gh)."""
import hashlib
from contextlib import nullcontext, contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gway_remote import android_canary_field as field

PR = 644
SHA = "a" * 40
RUN = 44789265881


class ProvenanceTests(unittest.TestCase):
    def fixture(self, directory):
        d = Path(directory)
        hashes = {}
        for name in field.FILES:
            data = b"APK " + name.encode()
            (d / name).write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        (d / "SHA256SUMS").write_text(
            "".join(f"{hashes[n]}  {n}\n" for n in field.FILES)
        )
        values = {
            "Repository": field.REPO, "Pull-Request": str(PR),
            "Source-Commit": SHA, "Canary-Overlay": "package-and-label-v1",
            "Package": field.APP, "Signing": "ephemeral Android debug certificate",
            "Test-Package": field.TEST, "Test-Runner": field.RUNNER,
            "Actions-Run": str(RUN),
        }
        (d / "PROVENANCE.txt").write_text(
            "".join(f"{k}: {v}\n" for k, v in values.items())
        )
        return d

    def test_exact_pair_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.fixture(tmp)
            self.assertEqual(len(field.provenance(d, pr=PR, sha=SHA, run_id=RUN)), 2)

    def test_rejects_changed_sha_or_unlisted_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.fixture(tmp)
            with self.assertRaises(field.CanaryError):
                field.provenance(d, pr=PR, sha="b" * 40, run_id=RUN)
            (d / "secret.txt").write_text("forbidden")
            with self.assertRaises(field.CanaryError):
                field.provenance(d, pr=PR, sha=SHA, run_id=RUN)

    def test_rejects_tampered_test_apk(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.fixture(tmp)
            (d / field.FILES[1]).write_bytes(b"modified")
            with self.assertRaises(field.CanaryError):
                field.provenance(d, pr=PR, sha=SHA, run_id=RUN)

    def test_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.fixture(tmp)
            p = d / field.FILES[1]
            p.unlink()
            p.symlink_to(d / field.FILES[0])
            with self.assertRaises(field.CanaryError):
                field.provenance(d, pr=PR, sha=SHA, run_id=RUN)


class UsbTests(unittest.TestCase):
    @patch.object(field, "command")
    def test_single_usb_and_no_emulator(self, cmd):
        cmd.side_effect = ["List of devices attached\nabc123 device usb:2-1 model:SM_G950F\n", "0\n"]
        self.assertEqual(field.usb(), "abc123")

    @patch.object(field, "command")
    def test_multiple_devices_rejected(self, cmd):
        cmd.return_value = (
            "List of devices attached\na device usb:2-1\nb device usb:2-2\n"
        )
        with self.assertRaises(field.CanaryError):
            field.usb()
        self.assertEqual(cmd.call_count, 1)

    @patch.object(field, "command")
    def test_tcp_device_rejected(self, cmd):
        cmd.return_value = "List of devices attached\n10.0.0.1:5555 device model:phone\n"
        with self.assertRaises(field.CanaryError):
            field.usb()

    @patch.object(field, "adb")
    def test_unconfirmed_lock_state_rejected(self, adb):
        adb.side_effect = ["mWakefulness=Awake", "mCurrentFocus=Launcher"]
        with self.assertRaisesRegex(field.CanaryError, "lock_state_unknown"):
            field.device_ready("serial")


class RunSelectionTests(unittest.TestCase):
    @patch.object(field, "gh")
    def test_only_approved_manual_run_and_current_pr(self, gh):
        gh.side_effect = [
            {"state": "open", "head": {
                "repo": {"full_name": field.REPO}, "sha": SHA}},
            {"workflow_runs": [
                {"id": RUN, "event": "workflow_dispatch", "head_branch": "main",
                 "status": "completed", "conclusion": "success"}]},
            {"artifacts": [{"name": f"android-canary-pr{PR}-{SHA[:12]}",
                            "expired": False, "workflow_run": {"id": RUN}}]},
        ]
        self.assertEqual(field.eligible_run(PR), (RUN, f"android-canary-pr{PR}-{SHA[:12]}", SHA))

    @patch.object(field, "gh")
    def test_rejects_pr_from_fork(self, gh):
        gh.return_value = {"state": "open", "head": {
            "repo": {"full_name": "attacker/fork"}, "sha": SHA}}
        with self.assertRaises(field.CanaryError):
            field.eligible_run(PR)


class UsbWakeGuardTests(unittest.TestCase):
    @patch.object(field, "adb")
    def test_restores_existing_global_mask_after_failure(self, adb):
        adb.side_effect = ["USB powered: true", "1", "", "3", "", "1"]
        with self.assertRaisesRegex(RuntimeError, "test_abort"):
            with field.keep_usb_screen_on("usb-device"):
                raise RuntimeError("test_abort")
        write_calls = [call.args for call in adb.call_args_list
                       if call.args[1:5] == ("shell", "settings", "put", "global")]
        self.assertEqual(write_calls[0][-2:], ("stay_on_while_plugged_in", "3"))
        self.assertEqual(write_calls[-1][-2:], ("stay_on_while_plugged_in", "1"))

    @patch.object(field, "adb")
    def test_does_not_mutate_if_stay_on_already_configured(self, adb):
        adb.side_effect = ["USB powered: true", "2"]
        with field.keep_usb_screen_on("usb-device"):
            pass
        self.assertEqual(adb.call_count, 2)

    @patch.object(field, "adb")
    def test_rejects_unpowered_usb(self, adb):
        adb.return_value = "USB powered: false"
        with self.assertRaisesRegex(field.CanaryError, "usb_power_unconfirmed"):
            with field.keep_usb_screen_on("usb-device"):
                pass
        self.assertEqual(adb.call_count, 1)

    @patch.object(field, "adb")
    def test_restore_missing_original_setting(self, adb):
        adb.side_effect = ["USB powered: true", "null", "", "2", "", "null"]
        with field.keep_usb_screen_on("usb-device"):
            pass
        self.assertTrue(any(call.args[1:5] == ("shell", "settings", "delete", "global")
                            for call in adb.call_args_list))


class InstrumentationTests(unittest.TestCase):
    @patch.object(field, "adb")
    def test_quotation_suite_selects_only_approved_class_and_requires_five(self, adb):
        with patch.object(field, "keep_usb_screen_on", return_value=nullcontext()):
            with patch.object(field, "device_ready", return_value=True):
                adb.return_value = "OK (5 tests)\nINSTRUMENTATION_CODE: -1\n"
                self.assertEqual(field.instrument("usb-device", suite="quotations"), 5)
                self.assertIn("com.arthexis.gwayremote.OdooQuotationRefreshTest",
                              adb.call_args_list[0].args)
                adb.return_value = "OK (4 tests)\nINSTRUMENTATION_CODE: -1\n"
                with self.assertRaisesRegex(field.CanaryError, "instrumentation_failed"):
                    field.instrument("usb-device", suite="quotations")

    @patch.object(field, "adb")
    def test_arbitrary_instrumentation_class_is_rejected(self, adb):
        with self.assertRaisesRegex(field.CanaryError, "unknown_test_suite"):
            field.instrument("usb-device", suite="arbitrary.Class")
        adb.assert_not_called()

    def test_suite_receipts_do_not_overwrite_baseline(self):
        self.assertNotEqual(field.state_path(), field.state_path("quotations"))
        self.assertNotEqual(field.state_path("opportunities"), field.state_path("quotations"))
        self.assertNotEqual(field.state_path("opportunities"), field.state_path())
        self.assertEqual(field.SUITES["opportunities"], ("com.arthexis.gwayremote.OdooOpportunityCopyTest", 2))

    @patch.object(field, "adb")
    def test_pass_requires_android_runner_success(self, adb):
        adb.return_value = "OK (6 tests)\nINSTRUMENTATION_CODE: -1\n"
        with patch.object(field, "keep_usb_screen_on", return_value=nullcontext()) as guard:
            with patch.object(field, "device_ready", return_value=True) as ready:
                self.assertEqual(field.instrument("usb-device", wake=True), 6)
        guard.assert_called_once_with("usb-device")
        ready.assert_called_once_with("usb-device", wake=True)
        self.assertTrue(any(
            "com.arthexis.gwayremote.canary.test/" in " ".join(map(str, call.args))
            for call in adb.call_args_list
        ))

    def test_rechecks_screen_inside_guard_before_instrumentation(self):
        calls = []
        @contextmanager
        def guard(serial):
            calls.append("guard_enter")
            try:
                yield
            finally:
                calls.append("guard_exit")
        def ready(serial, *, wake=False):
            calls.append("device_ready")
            self.assertTrue(wake)
            return False
        def adb(serial, *args, **kwargs):
            if args[:3] == ("shell", "am", "instrument"):
                calls.append("instrument")
                return "OK (6 tests)\\nINSTRUMENTATION_CODE: -1\\n"
            return ""
        with patch.object(field, "keep_usb_screen_on", side_effect=guard):
            with patch.object(field, "device_ready", side_effect=ready):
                with patch.object(field, "adb", side_effect=adb):
                    self.assertEqual(field.instrument("usb-device", wake=True), 6)
        self.assertEqual(calls, ["guard_enter", "device_ready", "instrument", "guard_exit"])

    @patch.object(field, "adb")
    def test_generic_output_is_not_pass(self, adb):
        adb.return_value = "Success"
        with patch.object(field, "keep_usb_screen_on", return_value=nullcontext()):
            with patch.object(field, "device_ready", return_value=True):
                with self.assertRaises(field.CanaryError):
                    field.instrument("usb-device")


if __name__ == "__main__":
    unittest.main()
