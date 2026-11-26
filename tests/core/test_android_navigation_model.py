import unittest

from gway_remote import android_navigation_model as model
from gway_remote.mcp_android import Device, TOOLS, call_tool


def node(text="", resource_id="", bounds="[0,0][100,30]", **flags):
    return {"text": text, "resource_id": resource_id, "bounds": bounds, **flags}


class NavigationModelTests(unittest.TestCase):
    def test_developer_screen_recognizes_only_adjacent_switch(self):
        tree = {"truncated": False, "elements": [
            node("Opciones de desarrollador"),
            node("Permanecer activo", bounds="[72,1419][521,1492]"),
            node(resource_id="android:id/switch_widget", bounds="[879,1472][1008,1538]", checked=False),
            node(resource_id="android:id/switch_widget", bounds="[879,1757][1008,1823]", checked=True),
        ]}
        result = model.observe(tree)
        self.assertEqual(result["screen"], "developer_options")
        self.assertEqual(result["controls"], [{"id": "stay_awake", "checked": False}])
        tree["elements"].append(node(resource_id="android:id/switch_widget",
                                     bounds="[800,1470][850,1530]", checked=True))
        self.assertEqual(model.observe(tree)["controls"], [])

    def test_partial_or_ambiguous_screen_never_identified(self):
        self.assertEqual(model.observe({"elements": [], "truncated": True})["status"], "incomplete")
        tree = {"truncated": False, "elements": [node("Ajustes"), node("Pantalla"),
            node(resource_id="com.android.settings.intelligence:id/search_src_text")]}
        self.assertEqual(model.observe(tree)["status"], "ambiguous")

    def test_route_is_directed_and_unknown_destination_has_no_route(self):
        route = model.route("settings", "developer_options")
        self.assertEqual([step["to"] for step in route], ["settings_search", "developer_options"])
        self.assertIsNone(model.route("developer_options", "settings"))
        self.assertIsNone(model.route("settings", "anything"))

    def test_provider_advertises_read_only_and_rejects_unknown_arguments(self):
        tool = next(t for t in TOOLS if t["name"] == "navigation_model")
        self.assertTrue(tool["annotations"]["readOnlyHint"])
        self.assertTrue(call_tool("navigation_model", {"destination": "invalid"})["isError"])

    def test_provider_reads_screen_and_rejects_screen_change(self):
        class FakeDevice(Device):
            def serial(self):
                return "fake"

            def screen_state(self, serial):
                return next(self.states)

            def ui_tree(self, serial):
                return {"truncated": False, "elements": [node("Ajustes"), node("Pantalla")]}

        device = FakeDevice()
        stable = {"screen_on": True, "locked": False, "rotation": 0}
        device.states = iter([stable, stable])
        result = device.invoke("navigation_model", {"destination": "developer_options"})
        self.assertEqual(result["screen"], "settings")
        self.assertEqual(len(result["route"]), 2)
        device.states = iter([stable, {**stable, "locked": True}])
        self.assertEqual(device.invoke("navigation_model", {})["status"], "screen_changed")


if __name__ == "__main__":
    unittest.main()
