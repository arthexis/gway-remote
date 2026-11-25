import json
import unittest
from unittest.mock import patch
from gway_remote import mobile, mobile_liturgia

class MobileLiturgiaTests(unittest.TestCase):
    def test_catalog_and_read_scope(self):
        entry = next(x for x in mobile.commands() if x["name"] == "liturgia-read")
        self.assertTrue(entry["read_only"])
        payload = {"schema_version": 1, "items": []}
        with patch.object(mobile_liturgia, "discover_installed_providers", return_value=()) as discover, patch.object(mobile_liturgia, "provider_call", return_value={"content": [{"type": "text", "text": json.dumps(payload)}]}) as call:
            self.assertEqual(mobile.execute("liturgia-read", {"tool": "translations", "arguments": {}}), payload)
            call.assert_called_once_with((), provider="liturgia", tool="translations", arguments={}, authorized_scope="read")

    def test_no_arbitrary_provider_or_scope(self):
        for params in ({"tool": "delete", "arguments": {}}, {"tool": "search", "arguments": {}, "provider": "odoo"}, {"tool": "search", "arguments": {}, "scope": "execute"}):
            with self.assertRaises(ValueError):
                mobile_liturgia.read(params)
