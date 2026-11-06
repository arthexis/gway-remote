import unittest

from gway_remote.mcp_catalog import ToolCatalogError, compose_catalog


class NodeOwnedCatalogTests(unittest.TestCase):
    def test_preserves_tool_contract(self):
        tool = {"name": "example", "description": "A tool",
                "inputSchema": {"type": "object", "properties": {}}}
        self.assertEqual(compose_catalog([tool]), [tool])

    def test_rejects_shadowing_across_sources(self):
        tool = {"name": "example", "inputSchema": {"type": "object"}}
        with self.assertRaises(ToolCatalogError):
            compose_catalog([tool], [tool])

    def test_rejects_malformed_tools(self):
        for item in ({"name": "", "inputSchema": {"type": "object"}},
                     {"name": "ok", "inputSchema": {"type": "string"}},
                     {"name": "ok"}):
            with self.subTest(item=item), self.assertRaises(ToolCatalogError):
                compose_catalog([item])


if __name__ == "__main__":
    unittest.main()
