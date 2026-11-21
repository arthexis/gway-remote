import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android/app/src/main/java/com/arthexis/gwayremote"


class ModuleArchitectureTests(unittest.TestCase):
    def test_activity_is_only_a_shell_entry_point(self):
        main = (ANDROID / "MainActivity.kt").read_text()
        screen = (ANDROID / "ui/shell/CompanionScreen.kt").read_text()
        self.assertIn("CompanionScreen(store, appearance)", main)
        self.assertNotIn("OperationPalette(", main)
        self.assertNotIn("OperationPanelHost(", main)
        self.assertNotIn("BenchmarkRunner(", main)
        self.assertNotIn("ApiClient(", main)
        self.assertNotIn("LocalPanelState(", main)
        self.assertIn("ModalNavigationDrawer(", screen)
        self.assertNotIn("OperationPalette(", screen)
        self.assertNotIn("LocalPanelHost(", screen)
        self.assertNotIn("PanelChrome(", screen)
        self.assertNotIn("Response", screen)
        self.assertIn("OperationModulePage(", screen)
        self.assertIn("package com.arthexis.gwayremote.ui.shell", screen)

    def test_all_registered_modules_own_an_independent_destination(self):
        registry = (ANDROID / "FeatureRegistry.kt").read_text()
        routes = (ANDROID / "ModuleRegistry.kt").read_text()
        screen = (ANDROID / "ui/shell/CompanionScreen.kt").read_text()
        for module in ("deployments", "github-health", "mcp-access", "odoo-quotations"):
            self.assertIn(f'FeatureSpec("{module}"', registry)
            self.assertIn(f'"{module}"', screen)
        self.assertIn("FeatureRegistry.features.filter", routes)
        self.assertIn("ModuleRegistry.modules.forEach", (ANDROID / "ui/shell/ModuleShell.kt").read_text())
        self.assertIn('"benchmark" -> ModulePage', screen)
        self.assertIn('BenchmarkModule(settings.endpoint, settings.token)', screen)
        self.assertIn("rememberAppUpdateController()", screen)
        self.assertIn("package com.arthexis.gwayremote.features.updates", (ANDROID / "features/updates/AppUpdateController.kt").read_text())
        self.assertIn("AppUpdateController(", (ANDROID / "features/updates/AppUpdateController.kt").read_text())

    def test_operation_modules_do_not_render_legacy_panel_chrome(self):
        source = (ANDROID / "features/operations/OperationModulePage.kt").read_text()
        self.assertIn("ModuleSystemContent(", source)
        self.assertIn("CsmsUnifiedPanel(", source)
        self.assertIn("ModuleNotificationsContent(", source)
        self.assertIn("AgentOpsPanel(", source)
        self.assertIn("DisposableEffect(id)", source)
        for legacy in ("OperationPalette(", "OperationPanelHost(", "PanelChrome(", "StandardPanel(", "LocalPanelHost("):
            self.assertNotIn(legacy, source)
        self.assertIn("operations::executeNotification", source)
        self.assertIn("ModuleOperationViewModel = viewModel()", source)

    def test_ui_and_feature_packages_use_shared_visual_contract(self):
        components = (ANDROID / "ui/components/ModulePage.kt").read_text()
        self.assertIn("fun ModulePage(", components)
        self.assertIn("fun ModuleHeader(", components)
        self.assertIn("fun ModuleLoading(", components)
        self.assertIn("fun ModuleNotice(", components)
        self.assertIn("fun ModuleActions(", components)
        shell = (ANDROID / "ui/shell/CompanionScreen.kt").read_text()
        self.assertIn('"github-health" -> ModulePage', shell)
        self.assertNotIn("ModuleScrollPage(", shell)
        pages = {
            "features/benchmark/BenchmarkModule.kt": "benchmark",
            "features/deployments/DeploymentsPanel.kt": "deployments",
            "features/githubhealth/GitHubHealthPanel.kt": "githubhealth",
            "features/odoo/OdooQuotationsPanel.kt": "odoo",
            "features/mcp/McpAccessPanel.kt": "mcp",
            "features/operations/OperationModulePage.kt": "operations",
        }
        for path, name in pages.items():
            with self.subTest(module=name):
                source = (ANDROID / path).read_text()
                self.assertIn(f"package com.arthexis.gwayremote.features.{name}", source)
                self.assertIn("ModuleHeader(", source)
        self.assertIn("ModulePage {", (ANDROID / "features/operations/OperationModulePage.kt").read_text())

    def test_internal_operations_and_backend_authority_stay_hidden(self):
        operations = (ANDROID / "OperationRegistry.kt").read_text()
        registry = (ANDROID / "FeatureRegistry.kt").read_text()
        routes = (ANDROID / "ModuleRegistry.kt").read_text()
        self.assertIn("OperationVisibility.PALETTE", registry)
        self.assertIn('visibility = OperationVisibility.INTERNAL', operations)
        self.assertIn("require(FeatureRegistry.features.all", routes)
        self.assertIn('"agent-ops"', (ANDROID / "features/operations/OperationModulePage.kt").read_text())
        self.assertNotIn("arbitrary-execute", routes)


if __name__ == "__main__":
    unittest.main()
