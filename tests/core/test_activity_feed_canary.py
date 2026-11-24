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


    def test_real_private_tls_and_denied_routes(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        import ssl
        import json
        from gway_remote.activity_feed_canary import _private_session
        from gway_remote.android_feed_canary import synthetic
        with TemporaryDirectory() as temp:
            roots = [Path(temp)/role for role in ("central","producer","backup")]
            for root in roots:
                root.mkdir(mode=0o700)
            with patch("gway_remote.activity_feed_canary.PORT",0):
                with _private_session(roots) as state:
                    url = "https://127.0.0.1:" + str(state["port"])
                    tls = ssl.create_default_context(cafile=str(state["cert"]))
                    with patch("gway_remote.android_feed_canary.PORT",state["port"]):
                        synthetic(state)
                    with urlopen(Request(url+"/api/feed/events",headers={
                            "Authorization":"Bearer "+state["reader"]}),context=tls,timeout=5) as response:
                        self.assertEqual(len(json.load(response)["items"]),1)
                    for path, token, code in (("/mcp",state["reader"],404),
                            ("/api/feed/events",state["writer"],401)):
                        with self.assertRaises(HTTPError) as failure:
                            urlopen(Request(url+path,headers={"Authorization":"Bearer "+token}),
                                    context=tls,timeout=5)
                        self.assertEqual(failure.exception.code,code)
                        failure.exception.close()
            self.assertTrue(all(not list(root.iterdir()) for root in roots))
