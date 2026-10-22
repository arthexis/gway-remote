"""Contract tests for approved deployment word selectors."""
import unittest

from gway_remote.deploy_dispatch import TARGETS, resolve_targets


class DeploySelectorTests(unittest.TestCase):
    def test_single_words(self):
        self.assertEqual(resolve_targets("reports"), ("ocpp-reports",))
        self.assertEqual(resolve_targets("sound"), ("gway-lcd-sound",))
        self.assertEqual(resolve_targets("lcd-sound"), ("gway-lcd-sound",))
        self.assertEqual(resolve_targets("kiosk"), ("gway-ap-kiosk",))
        self.assertEqual(resolve_targets("rfid"), ("gway-rfid",))

    def test_multi_match(self):
        self.assertEqual(resolve_targets("ocpp"), (
            "ocpp-csms", "ocpp-reports", "ocpp-simulator"))
        self.assertEqual(resolve_targets("gway"), tuple(
            name for name in TARGETS[1:] if name.startswith("gway-")))

    def test_word_boundaries_order_and_case(self):
        self.assertEqual(resolve_targets("GWAY-SOUND"), ("gway-lcd-sound",))
        self.assertEqual(resolve_targets("gway-sound"), ("gway-lcd-sound",))
        self.assertEqual(resolve_targets("ap-kiosk"), ("gway-ap-kiosk",))
        with self.assertRaises(ValueError):
            resolve_targets("way")

    def test_dynamic_allowlist_and_no_duplicates(self):
        catalog = ("gway-future-widget", "gway-future-widget", "gway-lcd-sound")
        self.assertEqual(resolve_targets("widget", catalog), ("gway-future-widget",))
        self.assertEqual(resolve_targets("gway", catalog),
                         ("gway-future-widget", "gway-lcd-sound"))
        with self.assertRaises(ValueError):
            resolve_targets("other", catalog)

    def test_invalid_and_unknown_inputs(self):
        for value in ("", "gway--sound", "gway/", "unsupported"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                resolve_targets(value)


if __name__ == "__main__":
    unittest.main()
