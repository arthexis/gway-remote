import unittest
from unittest.mock import patch
from gway_remote.activity_feed_canary import FeedOnlyHandler, PORT
from gway_remote.android_feed_canary import _has_mapping, tunnel, MAPPING

class CanaryBoundaryTests(unittest.TestCase):
    def test_existing_mapping_is_never_replaced(self):
        with patch("gway_remote.android_feed_canary.field.adb",return_value="UsbFfs "+MAPPING+" "+MAPPING) as adb:
            with self.assertRaises(RuntimeError):
                with tunnel("fake"):
                    self.fail("must refuse")
            self.assertEqual(adb.call_count,1)

    def test_tunnel_rollback_even_after_failure(self):
        with patch("gway_remote.android_feed_canary.field.adb",side_effect=["","", "UsbFfs "+MAPPING+" "+MAPPING,"",""]) as adb:
            with self.assertRaises(ValueError):
                with tunnel("fake"):
                    raise ValueError("fixture")
            self.assertEqual(adb.call_args_list[3].args[1:4],("reverse","--remove",MAPPING))

    def test_fixed_loopback_contract(self):
        self.assertEqual(PORT,18443)
        self.assertFalse(_has_mapping("UsbFfs tcp:80 tcp:80"))
