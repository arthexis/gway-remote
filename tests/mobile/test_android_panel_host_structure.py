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

    def test_installed_local_modules_are_wired_to_isolated_pages(self):
        main = (ANDROID / "MainActivity.kt").read_text()
        registry = (ANDROID / "FeatureRegistry.kt").read_text()
        modules = (ANDROID / "ModuleRegistry.kt").read_text()
        shell = (ANDROID / "ModuleShell.kt").read_text()
        for feature in ("deployments", "github-health", "mcp-access", "odoo-quotations"):
            self.assertIn(f'FeatureSpec("{feature}"', registry)
        self.assertIn("FeatureRegistry.features.filter", modules)
        self.assertIn("ModuleRegistry.modules.forEach", shell)
        self.assertIn("ModalNavigationDrawer(", main)
        self.assertIn("selectedModuleId = id", main)
        self.assertIn("localPanels = localPanels.open(id)", main)
        self.assertIn("LocalPanelHost(", main)
        self.assertNotIn("localPanels.toggle(", main)
        self.assertNotIn("quotationsOpen", main.split("ModalNavigationDrawer(")[1])
        local_host = (ANDROID / "panels/LocalPanelHost.kt").read_text()
        self.assertIn("PanelChrome(", local_host)
        self.assertIn('"deployments" -> DeploymentsPanel(endpoint, token)', local_host)
        self.assertIn('"github-health" -> GitHubHealthPanel(endpoint, token)', local_host)
        self.assertIn('"mcp-access" -> McpAccessPanel(', local_host)

    def test_removed_tasks_are_absent_from_specialized_registry(self):
        source = (ANDROID / "registry/PanelContentRegistry.kt").read_text()
        self.assertNotIn('"tasks" to', source)
        self.assertNotIn('"task-detail" to', source)
        self.assertIn('"agent-ops" to', source)

    def test_palette_remains_a_non_visible_compatibility_host(self):
        main = (ANDROID / "MainActivity.kt").read_text()
        palette = (ANDROID / "OperationPalette.kt").read_text()
        self.assertIn("showPalette = false", main)
        self.assertIn("if (showPalette)", palette)
        self.assertIn("OperationPanelHost(", palette)
        self.assertNotIn("extraActions = listOf(", main)
        self.assertNotIn("Text(\"Response\")", main.split("ModalNavigationDrawer(")[1])
        registry = (ANDROID / "FeatureRegistry.kt").read_text()
        self.assertIn("search(query).filter", registry)



if __name__ == "__main__":
    unittest.main()
