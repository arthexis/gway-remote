import unittest

from gway_remote.mcp_catalog import ToolCatalogError
from gway_remote.mcp_source_registry import SourceRegistration, compose_source_catalog

SHA = "a" * 40


def source(**changes):
    fields = dict(source_id="odoo", revision=SHA, executable="/opt/odoo/bin/mcp",
                  argv=("/opt/odoo/bin/mcp",), run_as="odoomcp", enabled=True)
    fields.update(changes)
    return SourceRegistration(**fields)


TOOL = {"name": "latest", "description": "Read latest",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True}}


class SourceRegistryTests(unittest.TestCase):
    def test_namespaced_composition(self):
        result = compose_source_catalog(
            [{"name": "agent_status", "inputSchema": {"type": "object"}}],
            [source()], {"odoo": [TOOL]})
        self.assertEqual([t["name"] for t in result], ["agent_status", "odoo__latest"])

    def test_default_disabled(self):
        registration = source(enabled=False)
        self.assertEqual(compose_source_catalog([], [registration], {}), [])
        with self.assertRaises(ToolCatalogError):
            compose_source_catalog([], [registration], {"odoo": [TOOL]})

    def test_unregistered_and_collision(self):
        with self.assertRaises(ToolCatalogError):
            compose_source_catalog([], [], {"odoo": [TOOL]})
        with self.assertRaises(ToolCatalogError):
            compose_source_catalog([], [source(), source()], {"odoo": [TOOL]})
        with self.assertRaises(ToolCatalogError):
            compose_source_catalog(
                [{"name": "odoo__latest", "inputSchema": {"type": "object"}}],
                [source()], {"odoo": [TOOL]})

    def test_rejects_permission_and_unpinned_or_unsafe_path(self):
        for changes in ({"permission": "execute"}, {"revision": "main"},
                        {"executable": "relative/path"}, {"executable": "/opt/../bin"},
                        {"argv": ("bash",)}, {"run_as": "root-user"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                source(**changes)

    def test_rejects_unsafe_source_tool(self):
        for change in ({"annotations": {"readOnlyHint": False}},
                       {"annotations": {"readOnlyHint": True, "destructiveHint": True}},
                       {"annotations": "read"},
                       {"name": "bad name"}, {"inputSchema": {"type": "string"}}):
            with self.subTest(change=change), self.assertRaises((ToolCatalogError, ValueError)):
                compose_source_catalog([], [source()], {"odoo": [{**TOOL, **change}]})


if __name__ == "__main__":
    unittest.main()
