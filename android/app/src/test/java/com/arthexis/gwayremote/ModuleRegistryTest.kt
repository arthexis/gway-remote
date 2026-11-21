package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class ModuleRegistryTest {
    @Test fun everyInstalledFeatureHasOneDedicatedDestination() {
        val all = ModuleRegistry.modules
        assertEquals(all.size, all.map { it.id }.distinct().size)
        assertEquals(
            FeatureRegistry.features.map { it.id }.toSet() + setOf(ModuleRegistry.HOME, ModuleRegistry.SETTINGS),
            all.map { it.id }.toSet()
        )
        assertTrue(all.all { it.destination is ModuleDestination.Screen })
        assertNull(ModuleRegistry.get("api-health")) // internal operations do not become modules
        assertNull(ModuleRegistry.get("lcd")) // private command; notifications is the module
        assertNull(ModuleRegistry.get("arbitrary-execute"))
    }

    @Test fun navigatingDoesNotOpenPanelsOrRunCommands() {
        val initial = ModuleNavigationState()
        val selected = initial.select("csms")
        assertEquals(ModuleRegistry.HOME, initial.selectedId)
        assertEquals("csms", selected.selectedId)
        assertEquals("csms", selected.select("not-an-installed-module").selectedId)
        assertEquals(ModuleRegistry.HOME, selected.select(ModuleRegistry.HOME).selectedId)
        assertEquals("notifications", selected.select("notifications").selectedId)
        assertEquals(ExecutionPolicy.EXPLICIT_INPUT,
            FeatureRegistry.get("notifications")!!.operation!!.policy)
        assertEquals(ExecutionPolicy.AUTO_READ,
            FeatureRegistry.get("csms")!!.operation!!.policy)
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsPlainHttpExternalDestination() {
        ModuleDestination.HttpsLink("http://customer.gelectriic.com/")
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsUrlWithEmbeddedUserInfo() {
        ModuleDestination.HttpsLink("https://user:secret@customer.gelectriic.com/")
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsInvalidAppPackage() {
        ModuleDestination.AndroidAppLink("https://customer.gelectriic.com/", "invalid package")
    }

    @Test fun externalTargetsAreExplicitAndCarryNoAppCredentials() {
        val url = "https://customer.gelectriic.com/"
        val link = ModuleDestination.HttpsLink(url)
        val appLink = ModuleDestination.AndroidAppLink(url, "com.example.dashboard")
        assertEquals(url, link.url)
        assertEquals("com.example.dashboard", appLink.packageName)
        assertTrue(ModuleRegistry.modules.none { it.destination !is ModuleDestination.Screen })
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsUnknownNativeModule() {
        AppModule("secret-shell", "Shell", "terminal", ModuleDestination.Screen("secret-shell"))
    }
}
