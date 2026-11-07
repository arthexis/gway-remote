"""Tool-scope contract shared by federation and gateway authorization."""
import unittest

from gway_remote.mcp_tool_scope import required_scope


class TestMcpToolScope(unittest.TestCase):
    def test_explicit_read_only(self):
        self.assertEqual(required_scope({"name": "search", "annotations": {"readOnlyHint": True}}), "read")

    def test_missing_annotations_require_execution(self):
        for tool in ({"name": "update"}, {"name": "update", "annotations": {}},
                     {"name": "update", "annotations": {"readOnlyHint": False}},
                     {"name": "update", "annotations": {"readOnlyHint": "true"}}):
            with self.subTest(tool=tool):
                self.assertEqual(required_scope(tool), "execute")

    def test_destructive_annotation_overrides_read_hint(self):
        self.assertEqual(required_scope({
            "name": "delete", "annotations": {"readOnlyHint": True, "destructiveHint": True}
        }), "execute")

    def test_malformed_declaration_rejected(self):
        with self.assertRaises(ValueError):
            required_scope(None)


if __name__ == "__main__":
    unittest.main()
