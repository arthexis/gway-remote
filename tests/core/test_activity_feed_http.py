"""Real loopback Watchtower handler, real isolated bearer verifier."""
import http.client
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest

from gway_remote.activity_feed import ActivityFeedStore
from gway_remote.activity_feed_http import ActivityFeedAPI, PATH
from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.mcp_bearer_gateway import make_server
from tests.core.test_activity_feed import event


class ActivityFeedHTTPTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.registry = BearerRegistry(root / "bearer.sqlite3")
        self.reader = self.registry.issue(scope="gway:read")
        self.writer = self.registry.issue(scope="gway:execute", operator_approved=True)
        self.other = self.registry.issue(scope="gway:execute", operator_approved=True)
        self.key = self.writer.split("_", 2)[1]
        self.grants = {self.key: {"enabled": True, "source": "/gway/deploy",
                        "nodes": ["gway-001"], "repositories": [None],
                        "types": ["deployment.completed"]}}
        self.verifier = BearerVerifier(root / "bearer.sqlite3")
        self.store = ActivityFeedStore(root / "feed.sqlite3")
        self.api = ActivityFeedAPI(self.store, self.verifier, lambda: self.grants)
        self.server = make_server(("127.0.0.1", 0), self.verifier,
                                  "http://127.0.0.1:19011/mcp", "test", activity_feed=self.api)
        self.thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path=PATH, token=None, value=None, raw=None, extra=None):
        headers = {"Content-Type": "application/json"} if method == "POST" else {}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        headers.update(extra or {})
        data = raw if raw is not None else (json.dumps(value).encode() if value is not None else None)
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, body=data, headers=headers)
            response = connection.getresponse()
            body = response.read()
            return response.status, json.loads(body) if body else None
        finally:
            connection.close()

    def test_publish_replay_conflict_and_read(self):
        status, item = self.request("POST", token=self.writer, value=event())
        self.assertEqual(status, 201)
        self.assertNotIn("producer", item)
        self.assertEqual(self.request("POST", token=self.writer, value=event()), (200, item))
        changed = event()
        changed["data"]["title"] = "Changed"
        self.assertEqual(self.request("POST", token=self.writer, value=changed)[0], 409)
        self.assertEqual(self.request("GET", token=self.reader)[1]["items"], [item])
        self.assertEqual(self.request("GET", PATH + "/1", token=self.writer), (200, item))
        self.assertEqual(self.request("GET", PATH + "/99", token=self.reader)[0], 404)

    def test_denial_no_write_and_revocation(self):
        self.assertEqual(self.request("GET")[0], 401)
        self.assertEqual(self.request("POST", token=self.reader, value=event())[0], 403)
        self.assertEqual(self.request("POST", token=self.other, value=event())[0], 403)
        for field, value in (("node", "gway-004"), ("repository", "other/repo")):
            forged = event()
            forged["data"][field] = value
            self.assertEqual(self.request("POST", token=self.writer, value=forged)[0], 403)
        forged = event()
        forged["source"] = "/other"
        self.assertEqual(self.request("POST", token=self.writer, value=forged)[0], 403)
        self.grants[self.key]["enabled"] = False
        self.assertEqual(self.request("POST", token=self.writer, value=event())[0], 403)
        self.grants[self.key]["enabled"] = True
        self.registry.revoke(self.key)
        self.assertEqual(self.request("POST", token=self.writer, value=event())[0], 401)
        self.assertEqual(self.store.list_after()["items"], [])

    def test_invalid_body_and_queries(self):
        for raw, status in ((b'{"id":"a","id":"b"}', 400), (b"x" * 16385, 413),
                            (b"[" * 1500, 400), (b"\xff", 400)):
            self.assertEqual(self.request("POST", token=self.writer, raw=raw)[0], status)
        for query in ("?limit=51", "?after=1&before=2", "?after=1&after=2", "?unknown=x"):
            self.assertEqual(self.request("GET", PATH + query, token=self.reader)[0], 400)
        self.assertEqual(self.request("GET", token=self.reader, extra={"Origin": "https://example.com"})[0], 403)
        self.assertEqual(self.store.list_after()["items"], [])

    def test_disabled_preserves_existing_routes(self):
        self.server.activity_feed = None
        self.assertEqual(self.request("GET", token=self.reader)[0], 405)
        self.assertEqual(self.request("POST", token=self.writer, value=event())[0], 404)
        self.assertEqual(self.store.list_after()["items"], [])

    def test_narrow_producer_scope_cannot_read_or_execute(self):
        with self.assertRaises(PermissionError):
            self.registry.issue(scope="gway:feed-publish")
        producer = self.registry.issue(scope="gway:feed-publish", operator_approved=True)
        key = producer.split("_", 2)[1]
        self.grants[key] = dict(self.grants[self.key])
        self.assertFalse(self.verifier.verify(producer, required_scope="gway:read"))
        self.assertFalse(self.verifier.verify(producer, required_scope="gway:execute"))
        self.assertFalse(self.verifier.verify(producer, required_scope="gway:lcd-sound"))
        self.assertEqual(self.request("GET", token=producer)[0], 401)
        self.assertEqual(self.request("POST", "/mcp", token=producer, value={})[0], 401)
        self.assertEqual(self.request("POST", token=producer, value=event())[0], 201)
        self.registry.revoke(key)
        self.assertEqual(self.request("POST", token=producer, value=event())[0], 401)

    def test_publisher_root_binding_and_rotation(self):
        root = self.registry.issue(scope="gway:feed-publish", operator_approved=True)
        key = root.split("_", 2)[1]
        self.grants[key] = dict(self.grants[self.key])
        child = self.registry.issue(scope="gway:feed-publish", parent_id=key)
        extra = {"X-Gway-Feed-Principal": key}
        self.assertEqual(self.request("POST", token=child, value=event(), extra=extra)[0], 201)
        rotated = self.registry.issue(scope="gway:feed-publish", parent_id=key)
        self.registry.revoke(child.split("_", 2)[1])
        self.assertEqual(self.request("POST", token=rotated, value=event(), extra=extra)[0], 200)
        self.assertEqual(self.request("POST", token=rotated, value=event("new"),
                                      extra={"X-Gway-Feed-Principal": self.key})[0], 403)
        self.assertEqual(len(self.store.list_after()["items"]), 1)

    def rpc(self, name, arguments, token):
        return self.request("POST", "/mcp", token=token, value={"jsonrpc": "2.0", "id": 1,
            "method": "tools/call", "params": {"name": name, "arguments": arguments}})

    def test_feed_mcp_and_json_export(self):
        self.assertEqual(self.rpc("feed__publish", {"event": event()}, self.reader)[0], 401)
        status, denied = self.rpc("feed__publish", {"event": event()}, self.other)
        self.assertEqual(status, 200)
        self.assertTrue(denied["result"]["isError"])
        status, reply = self.rpc("feed__publish", {"event": event()}, self.writer)
        self.assertEqual(status, 200)
        self.assertFalse(reply["result"]["isError"])
        for tool, args in (("feed__list", {}), ("feed__get", {"seq": 1}), ("feed__summary", {})):
            status, reply = self.rpc(tool, args, self.reader)
            self.assertEqual(status, 200)
            self.assertFalse(reply["result"]["isError"])
        self.assertEqual(self.request("GET", "/api/feed.json")[0], 401)
        status, feed = self.request("GET", "/api/feed.json", token=self.reader)
        self.assertEqual(status, 200)
        self.assertEqual(feed["version"], "https://jsonfeed.org/version/1.1")
        self.assertEqual(feed["items"][0]["id"], "1")
        self.assertNotIn("producer", feed["items"][0])
        self.server.activity_feed = None
        self.assertEqual(self.rpc("feed__list", {}, self.reader)[0], 403)

    def test_feed_catalog_is_local_and_opt_in(self):
        from gway_remote.mcp_bearer_gateway import effective_catalog
        tools, projection = effective_catalog([], activity_feed=self.api)
        rows = {r["name"]: r for r in projection["tools"]}
        self.assertEqual(rows["feed__publish"]["required_scope"], "gway:execute")
        self.assertEqual(rows["feed__list"]["required_scope"], "gway:read")
        self.assertFalse(any(t["name"].startswith("feed__") for t in effective_catalog([])[0]))
        with self.assertRaises(ValueError):
            effective_catalog([{"name": "feed__list"}])
