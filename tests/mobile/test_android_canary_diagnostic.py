"""No-device tests of privacy-preserving Android canary instrumentation receipts."""
import unittest
from unittest.mock import patch

from gway_remote import android_canary_diagnostic
from gway_remote.android_canary_diagnostic import summarize


class AndroidCanaryDiagnosticsTests(unittest.TestCase):
    def test_names_known_failures_without_stack_text(self):
        sample = (
            "INSTRUMENTATION_STATUS: class=com.arthexis.gwayremote.ModuleNavigationComposeTest\n"
            "INSTRUMENTATION_STATUS: test=drawerSelectsAnEntireModuleWithoutOpeningASecondPanel\n"
            "INSTRUMENTATION_STATUS_CODE: 1\n"
            "INSTRUMENTATION_STATUS: stack=Private UI content should not escape\n"
            "INSTRUMENTATION_STATUS_CODE: -2\n"
            "FAILURES!!! Tests run: 1, Failures: 1\n"
            "INSTRUMENTATION_CODE: -1\n"
        )
        data = summarize(sample)
        self.assertEqual(data["failed_status"], 1)
        self.assertEqual(data["footer_failures"], 1)
        self.assertEqual(data["failed_tests"], [
            "ModuleNavigationComposeTest.drawerSelectsAnEntireModuleWithoutOpeningASecondPanel"
        ])
        self.assertNotIn("Private UI", str(data))

    def test_success_and_unknown_test_are_bounded(self):
        sample = (
            "INSTRUMENTATION_STATUS: class=com.example.Unknown\n"
            "INSTRUMENTATION_STATUS: test=other\n"
            "INSTRUMENTATION_STATUS_CODE: -2\n"
            "OK (4 tests)\nINSTRUMENTATION_CODE: -1\n"
        )
        data = summarize(sample)
        self.assertEqual(data["footer_test_count"], 4)
        self.assertEqual(data["failed_tests"], ["unidentified_test_failure"])
        self.assertEqual(data["instrumentation_code"], -1)


class DiagnosticSourceGuardTests(unittest.TestCase):
    def test_unallowlisted_pr_is_rejected_without_device_access(self):
        with patch("sys.argv", ["android-canary-diagnostic", "--reinstall-pr", "999"]):
            with patch.object(android_canary_diagnostic.field, "usb") as usb:
                with self.assertRaises(SystemExit):
                    android_canary_diagnostic.main()
                usb.assert_not_called()


if __name__ == "__main__":
    unittest.main()
