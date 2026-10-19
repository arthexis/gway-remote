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
        self.assertIn("ConfirmPanelAction(", host)

    def test_search_and_actions_remain_in_palette(self):
        palette = (ANDROID / "OperationPalette.kt").read_text()
        self.assertIn("FeatureRegistry.search(filter)", palette)
        self.assertIn("PaletteActionRows(actions, columns)", palette)


if __name__ == "__main__":
    unittest.main()
