import unittest
from gway_remote.mcp_bridge_gateway_session import gateway_bridge_session


class Sessions:
    def __init__(self):
        self.events = []
    def register(self, *, token, audience):
        self.events.append(("register", token, audience))
        return "session"
    def revoke(self, session_id):
        self.events.append(("revoke", session_id))


class GatewaySessionTests(unittest.TestCase):
    def test_request_scoped_cleanup(self):
        manager = Sessions()
        with gateway_bridge_session(manager, bearer="verified", audience="gway-001") as sid:
            self.assertEqual(sid, "session")
            self.assertEqual(len(manager.events), 1)
        self.assertEqual(manager.events[-1], ("revoke", "session"))

    def test_exception_still_releases(self):
        manager = Sessions()
        with self.assertRaisesRegex(RuntimeError, "handler failed"):
            with gateway_bridge_session(manager, bearer="verified", audience="gway-001"):
                raise RuntimeError("handler failed")
        self.assertEqual(manager.events[-1], ("revoke", "session"))


if __name__ == "__main__":
    unittest.main()
