"""No-device tests of privacy-preserving Android canary instrumentation receipts."""
import unittest

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


if __name__ == "__main__":
    unittest.main()
