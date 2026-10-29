"""Deterministic tests for operator-issued MCP bearer authority."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from gway_remote.mcp_bearer import BearerRegistry

class BearerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "db" / "creds.sqlite3"
        self.reg = BearerRegistry(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_issue_verify_revoke(self):
        token = self.reg.issue()
        self.assertTrue(self.reg.verify(token))
        self.assertFalse(self.reg.verify(token + "x"))
        self.assertFalse(self.reg.verify("other"))
        self.assertFalse(self.reg.verify(token, required_scope="gway:submit"))
        key_id = token.split("_")[1]
        self.assertTrue(self.reg.revoke(key_id))
        self.assertFalse(self.reg.verify(token))
        self.assertFalse(self.reg.revoke(key_id))

    def test_expiration(self):
        with patch("gway_remote.mcp_bearer.time.time", return_value=1000):
            token = self.reg.issue(lifetime=60)
        with patch("gway_remote.mcp_bearer.time.time", return_value=1060):
            self.assertFalse(self.reg.verify(token))

    def test_scope_and_lifetime_rejection(self):
        with self.assertRaises(ValueError):
            self.reg.issue(scope="gway:submit")
        with self.assertRaises(ValueError):
            self.reg.issue(lifetime=1)

    def test_secure_mode(self):
        self.reg.issue()
        self.assertEqual(self.db.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.db.parent.stat().st_mode & 0o777, 0o700)

if __name__ == "__main__":
    unittest.main()
