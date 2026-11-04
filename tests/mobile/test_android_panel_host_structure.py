import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android/app/src/main/java/com/arthexis/gwayremote"


class PanelHostStructureTests(unittest.TestCase):
    def test_palette_delegates_panels_without_id_specific_branches(self):
        palette = (ANDROID / "OperationPalette.kt").read_text()
        host = (ANDROID / "panels/OperationPanelHost.kt").read_text()
        self.assertIn("OperationPanelHost(", palette)
        self.assertNotIn("state.panels.forEachIndexed", palette)
        self.assertNotIn('panel.id == "simulator-discover"', palette)
        self.assertNotIn('panel.id == "benchmark"', palette)
        self.assertIn("state.panels.forEachIndexed", host)
        self.assertIn("StandardPanel(", host)
        self.assertIn("PanelContent(", host)
        self.assertIn("PanelActions(", host)
        self.assertNotIn("simulator", host.lower())

    def test_home_local_panel_actions_are_wired(self):
        main = (ANDROID / "MainActivity.kt").read_text()
        registry = (ANDROID / "FeatureRegistry.kt").read_text()
        for feature in ("deployments", "github-health"):
            self.assertIn(f'id = "{feature}"', main)
            self.assertIn(f'FeatureSpec("{feature}"', registry)
        self.assertIn("deploymentsOpen = !deploymentsOpen", main)
        self.assertIn("if (deploymentsOpen)", main)

    def test_removed_tasks_are_absent_from_specialized_registry(self):
        source = (ANDROID / "registry/PanelContentRegistry.kt").read_text()
        self.assertNotIn('"tasks" to', source)
        self.assertNotIn('"task-detail" to', source)
        self.assertIn('"agent-ops" to', source)

    def test_search_and_actions_remain_in_palette(self):
        palette = (ANDROID / "OperationPalette.kt").read_text()
        self.assertIn("FeatureRegistry.visible(filter, showSecondary)", palette)
        self.assertIn("showSecondary = !showSecondary", palette)
        self.assertIn("More tools and settings", palette)
        registry = (ANDROID / "FeatureRegistry.kt").read_text()
        self.assertIn("search(query).filter", registry)
        self.assertIn("query.isNotBlank() || showSecondary", registry)
        self.assertIn("PaletteActionRows(actions + dynamicActions, columns)", palette)
        self.assertIn("FeatureRegistry.get(action.id) == null", palette)
        self.assertIn("action.label.contains(filter, ignoreCase = true)", palette)


if __name__ == "__main__":
    unittest.main()
