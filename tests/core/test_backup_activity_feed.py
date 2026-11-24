import unittest
from gway_remote.backup_activity_feed import backup_event

class BackupFeedTests(unittest.TestCase):
    def test_opaque_identity_and_distinct_verification(self):
        args = dict(node="gway-001",run_id="a"*32,at="2026-11-24T10:00:00Z")
        first = backup_event("/test",outcome="created",**args)
        self.assertEqual(first,backup_event("/test",outcome="created",**args))
        verified = backup_event("/test",outcome="verified",**args)
        self.assertNotEqual(first["id"],verified["id"])
        self.assertEqual(first["data"]["severity"],"info")
        self.assertEqual(verified["data"]["severity"],"success")
        with self.assertRaises(ValueError):
            backup_event("/test",outcome="created",**{**args,"run_id":"/private/path"})
