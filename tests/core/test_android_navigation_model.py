import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from gway_remote import android_navigation_model as model
from gway_remote.mcp_android import Device, TOOLS, call_tool


def node(text="", resource_id="", bounds="[0,0][100,30]", **flags):
    return {"text": text, "resource_id": resource_id, "bounds": bounds,
            "package": "com.android.settings", **flags}


class NavigationModelTests(unittest.TestCase):
    def test_developer_screen_recognizes_only_adjacent_switch(self):
        tree = {"truncated": False, "elements": [
            node("Opciones de desarrollador"),
            node("Permanecer activo", resource_id="android:id/title", ancestors=[2, 1, 0], bounds="[72,1419][521,1492]"),
            node(resource_id="android:id/switch_widget", bounds="[879,1472][1008,1538]", checked=False, checkable=True, ancestors=[3, 1, 0]),
            node(resource_id="android:id/switch_widget", bounds="[879,1757][1008,1823]", checked=True, checkable=True, ancestors=[5, 4, 0]),
        ]}
        result = model.observe(tree)
        self.assertEqual(result["screen"], "developer_options")
        self.assertEqual(result["controls"], [{"id": "stay_awake", "checked": False}])
        tree["elements"].append(node(resource_id="android:id/switch_widget",
                                     bounds="[800,1470][850,1530]", checked=True, checkable=True, ancestors=[6, 1, 0]))
        self.assertEqual(model.observe(tree)["controls"], [])

    def test_partial_or_ambiguous_screen_never_identified(self):
        self.assertEqual(model.observe({"elements": [], "truncated": True})["status"], "incomplete")
        tree = {"truncated": False, "elements": [node("Ajustes"), node("Pantalla"),
            node(resource_id="com.android.settings.intelligence:id/search_src_text", package="com.android.settings.intelligence")]}
        self.assertEqual(model.observe(tree)["status"], "ambiguous")

    def test_route_is_directed_and_unknown_destination_has_no_route(self):
        route = model.route("settings", "developer_options")
        self.assertEqual([step["to"] for step in route], ["settings_search", "settings_search_results", "developer_options"])
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

            def ui_tree(self, serial, *, navigation_details=False):
                return next(self.trees)

        device = FakeDevice()
        stable = {"screen_on": True, "locked": False, "rotation": 0}
        settings = {"truncated": False, "elements": [node("Ajustes"), node("Pantalla")]}
        device.trees = iter([settings, settings])
        device.states = iter([stable, stable])
        result = device.invoke("navigation_model", {"destination": "developer_options"})
        self.assertEqual(result["screen"], "settings")
        self.assertEqual(len(result["route"]), 3)
        device.trees = iter([settings, settings])
        device.states = iter([stable, {**stable, "locked": True}])
        self.assertEqual(device.invoke("navigation_model", {})["status"], "screen_changed")
        device.trees = iter([settings, {"truncated": False, "elements": []}])
        device.states = iter([stable, stable])
        self.assertEqual(device.invoke("navigation_model", {})["status"], "screen_changed")


    def test_semantic_transition_dispatches_only_after_two_matching_observations(self):
        search_id = "com.android.settings.intelligence:id/search_src_text"
        def search(query, *extra):
            return {"truncated": False, "elements": [
                node(query, search_id, package="com.android.settings.intelligence",
                     enabled=True, focused=True), *extra]}
        initial = search("")
        results = search("Permanecer activo", node("Permanecer activo",
                         "com.android.settings.intelligence:id/result",
                         package="com.android.settings.intelligence",
                         enabled=True, clickable=True))
        results["elements"].append(node("Opciones de desarrollador",
            "com.android.settings.intelligence:id/breadcrumb",
            package="com.android.settings.intelligence"))
        class FakeDevice(Device):
            def serial(self):
                return "fake"
            def size(self, serial):
                return (1080, 2220)
            def screen_state(self, serial):
                return {"screen_on": True, "locked": False, "rotation": 0}
            def ui_tree(self, serial, *, navigation_details=False):
                return next(self.trees)
            def adb(self, serial, *args, **kwargs):
                self.calls.append(args)
        device = FakeDevice()
        device.calls = []
        device.trees = iter([initial, initial, results, results])
        self.assertEqual(device.semantic_transition("settings_search", "settings_search_results"),
                         {"status": "confirmed", "dispatched": True})
        self.assertEqual(device.calls, [("shell", "input", "text", "Permanecer%sactivo")])
        device.calls.clear()
        device.trees = iter([initial, results])
        self.assertEqual(device.semantic_transition("settings_search", "settings_search_results"),
                         {"status": "unconfirmed", "dispatched": False, "reason": "target_changed"})
        self.assertEqual(device.calls, [])
        device.trees = iter([initial, initial, initial, initial, initial])
        self.assertEqual(device.semantic_transition("settings_search", "settings_search_results"),
                         {"status": "unconfirmed", "dispatched": True, "reason": "destination_unconfirmed"})
        self.assertEqual(len(device.calls), 1)

    def test_search_result_rejects_nonunique_target(self):
        search_id = "com.android.settings.intelligence:id/search_src_text"
        field = node("Permanecer activo", search_id,
                     package="com.android.settings.intelligence")
        result = node("Permanecer activo", "com.android.settings.intelligence:id/result",
                      package="com.android.settings.intelligence", enabled=True, clickable=True)
        crumb = node("Opciones de desarrollador", "com.android.settings.intelligence:id/breadcrumb",
                     package="com.android.settings.intelligence")
        tree = {"truncated": False, "elements": [field, result, crumb]}
        self.assertEqual(model.transition_target(tree, "settings_search_results",
                                                 "developer_options"),
                         ("tap_target", {"resource_id": result["resource_id"]}))
        tree["elements"].append(dict(result))
        self.assertIsNone(model.transition_target(tree, "settings_search_results",
                                                  "developer_options"))
        self.assertIsNone(model.transition_target(tree, "settings", "settings_search"))


    def test_physical_history_is_not_a_result(self):
        package = "com.android.settings.intelligence"
        field = node("Buscar", package + ":id/search_src_text", package=package,
                     enabled=True, focused=True)
        history = node("Búsquedas recientes", package + ":id/saved_query_header_layout",
                       package=package)
        old_title = node("Permanecer activo", "android:id/title", package=package,
                         clickable=False, enabled=True)
        tree = {"truncated": False, "elements": [field, history, old_title]}
        self.assertEqual(model.observe(tree)["screen"], "settings_search")
        self.assertEqual(model.transition_target(tree, "settings_search", "settings_search_results"),
                         ("text", {"value": "Permanecer activo"}))
        field["text"] = "Permanecer activo"
        self.assertEqual(model.observe(tree)["status"], "unknown")
        self.assertIsNone(model.transition_target(tree, "settings_search_results", "developer_options"))
        field["text"] = "Buscar"
        field["focused"] = False
        self.assertIsNone(model.transition_target(tree, "settings_search", "settings_search_results"))

    def _physical_result(self):
        package = "com.android.settings.intelligence"
        return {"truncated": False, "elements": [
            node("Permanecer activo", package + ":id/search_src_text", package=package),
            node(resource_id="", package=package, node_index=10, ancestors=[8, 0],
                 enabled=True, clickable=True, scrollable=False, checkable=False,
                 bounds="[0,276][1080,554]"),
            node("Opciones de desarrollador", package + ":id/breadcrumb", package=package,
                 node_index=12, ancestors=[11, 10, 8, 0], clickable=False,
                 bounds="[72,318][526,386]"),
            node("Permanecer activo", "android:id/title", package=package,
                 node_index=13, ancestors=[11, 10, 8, 0], enabled=True, clickable=False,
                 bounds="[72,386][521,459]"),
            node("Description", "android:id/summary", package=package,
                 node_index=14, ancestors=[11, 10, 8, 0], clickable=False),
        ]}

    def test_physical_result_resolves_anonymous_clickable_row(self):
        tree = self._physical_result()
        self.assertEqual(model.observe(tree)["screen"], "settings_search_results")
        name, args = model.transition_target(tree, "settings_search_results", "developer_options")
        self.assertEqual(name, "tap_result")
        self.assertEqual(model.result_point(args, 1080, 2220), (296, 422))
        self.assertIsNone(model.result_point(args, 800, 2220))

    def test_result_ancestor_fails_closed_for_unsafe_or_ambiguous_rows(self):
        for flags in ({"enabled": False}, {"scrollable": True}, {"checkable": True},
                      {"package": "other"}, {"bounds": "[0,276][100,554]"}):
            with self.subTest(flags=flags):
                tree = self._physical_result()
                tree["elements"][1].update(flags)
                self.assertIsNone(model.transition_target(tree, "settings_search_results", "developer_options"))
        for extra in (node("Other", "android:id/title", ancestors=[10]),
                      node(resource_id="other:id/button", ancestors=[10], clickable=True),
                      node(resource_id="duplicate", node_index=10)):
            tree = self._physical_result()
            tree["elements"].append(extra)
            self.assertIsNone(model.transition_target(tree, "settings_search_results", "developer_options"))
        tree = self._physical_result()
        tree["elements"][2]["ancestors"] = [99]
        self.assertIsNone(model.transition_target(tree, "settings_search_results", "developer_options"))
        tree = self._physical_result()
        tree["truncated"] = True
        self.assertIsNone(model.transition_target(tree, "settings_search_results", "developer_options"))

    def test_result_dispatch_checks_stable_structural_target_and_verifies_destination(self):
        class FakeDevice(Device):
            def serial(self):
                return "fake"
            def size(self, serial):
                return (1080, 2220)
            def screen_state(self, serial):
                return {"screen_on": True, "locked": False, "rotation": 0}
            def ui_tree(self, serial, *, navigation_details=False):
                return next(self.trees)
            def adb(self, serial, *args, **kwargs):
                self.calls.append(args)
        device = FakeDevice()
        device.calls = []
        initial = self._physical_result()
        done = {"truncated": False, "elements": [node("Opciones de desarrollador"),
                                                  node("Permanecer activo")]}
        device.trees = iter([initial, initial, done, done])
        self.assertEqual(device.semantic_transition("settings_search_results", "developer_options"),
                         {"status": "confirmed", "dispatched": True})
        self.assertEqual(device.calls, [("shell", "input", "tap", 296, 422)])
        device.calls.clear()
        moved = self._physical_result()
        moved["elements"][3]["bounds"] = "[72,390][521,463]"
        device.trees = iter([initial, moved])
        self.assertEqual(device.semantic_transition("settings_search_results", "developer_options"),
                         {"status": "unconfirmed", "dispatched": False, "reason": "target_changed"})
        self.assertEqual(device.calls, [])
        device.trees = iter([initial, initial, initial, initial, initial])
        self.assertEqual(device.semantic_transition("settings_search_results", "developer_options"),
                         {"status": "unconfirmed", "dispatched": True, "reason": "destination_unconfirmed"})
        self.assertEqual(len(device.calls), 1)

    def test_private_navigation_tree_retains_anonymous_row_but_public_tree_does_not(self):
        package = "com.android.settings.intelligence"
        xml = f"""<hierarchy><node package="{package}" clickable="true" enabled="true"
            bounds="[0,276][1080,554]"><node package="{package}" text="Permanecer activo"
            resource-id="android:id/title" enabled="true" bounds="[72,386][521,459]"/>
            </node></hierarchy>""".encode()
        class FakeDevice(Device):
            def adb(self, serial, *args, **kwargs):
                return xml if args[:2] == ("shell", "cat") else b""
        device = FakeDevice()
        public = device.ui_tree("fake")
        private = device.ui_tree("fake", navigation_details=True)
        self.assertEqual(len(public["elements"]), 1)
        self.assertNotIn("node_index", public["elements"][0])
        self.assertEqual(len(private["elements"]), 2)
        self.assertEqual(private["elements"][0]["resource_id"], "")
        self.assertIn(private["elements"][0]["node_index"], private["elements"][1]["ancestors"])


    def test_transition_reports_predispatch_rejection_and_uncertain_adb(self):
        package = "com.android.settings.intelligence"
        initial = {"truncated": False, "elements": [
            node("Buscar", package + ":id/search_src_text", package=package,
                 enabled=True, focused=True)]}
        results = self._physical_result()
        class FakeDevice(Device):
            def serial(self):
                return "fake"
            def size(self, serial):
                return (1080, 2220)
            def screen_state(self, serial):
                return {"screen_on": True, "locked": False, "rotation": 0}
            def ui_tree(self, serial, *, navigation_details=False):
                value = next(self.trees)
                if isinstance(value, Exception):
                    raise value
                return value
            def adb(self, serial, *args, **kwargs):
                self.calls.append(args)
                if self.fail_dispatch:
                    raise TimeoutError("private detail")
        dev = FakeDevice()
        dev.calls = []
        dev.fail_dispatch = False
        edge = ("settings_search", "settings_search_results")
        dev.trees = iter([results])
        self.assertEqual(dev.semantic_transition(*edge),
            {"status": "unconfirmed", "dispatched": False, "reason": "source_not_actionable"})
        dev.trees = iter([initial, results])
        self.assertEqual(dev.semantic_transition(*edge),
            {"status": "unconfirmed", "dispatched": False, "reason": "target_changed"})
        dev.trees = iter([TimeoutError("private detail")])
        self.assertEqual(dev.semantic_transition(*edge),
            {"status": "unconfirmed", "dispatched": False, "reason": "preflight_error"})
        self.assertEqual(dev.calls, [])
        dev.fail_dispatch = True
        dev.trees = iter([initial, initial])
        self.assertEqual(dev.semantic_transition(*edge),
            {"status": "unconfirmed", "dispatched": True, "reason": "dispatch_uncertain"})
        self.assertEqual(len(dev.calls), 1)
        dev.fail_dispatch = False
        dev.trees = iter([initial, initial, TimeoutError("private detail")])
        self.assertEqual(dev.semantic_transition(*edge),
            {"status": "unconfirmed", "dispatched": True, "reason": "verification_error"})
        self.assertEqual(len(dev.calls), 2)
        dev.trees = iter([initial, initial, initial, results, results])
        self.assertEqual(dev.semantic_transition(*edge),
            {"status": "confirmed", "dispatched": True})
        self.assertEqual(len(dev.calls), 3)

    def test_provider_device_session_rejects_concurrent_physical_calls(self):
        from gway_remote import mcp_android as android
        from gway_remote import android_scenario_runner as scenarios
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "receipts"
            with patch.object(scenarios, "_receipt_root", return_value=root):
                with android._device_session():
                    with patch.object(android, "Device") as device:
                        response = android.call_tool("key", {"key": "HOME"})
                        self.assertTrue(response["isError"])
                        self.assertIn("device_busy", response["content"][0]["text"])
                        device.assert_not_called()
                    preview = android.call_tool("scenario_preview", {
                        "scenario_id": "developer-options-from-search-v1"})
                    self.assertFalse(preview.get("isError", False))
                with android._device_session():
                    pass


if __name__ == "__main__":
    unittest.main()
