package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class FeatureRegistryTest {
    @Test fun paletteOnlyExposesVisibleOperationsAndLocalActions() {
        val features = FeatureRegistry.features
        assertEquals(features.size, features.map { it.id }.distinct().size)
        assertEquals(
            OperationRegistry.operations.filter { it.visibility == OperationVisibility.PALETTE }.map { it.id }.toSet(),
            features.filter { it.kind == FeatureKind.OPERATION }.map { it.id }.toSet()
        )
        assertTrue(features.filter { it.kind == FeatureKind.LOCAL_PANEL }.all { it.operation == null })
        assertTrue(features.filter { it.kind == FeatureKind.OPERATION }.all {
            it.operation?.visibility == OperationVisibility.PALETTE
        })
    }

    @Test fun internalOperationsCannotBeOpenedFromThePalette() {
        OperationRegistry.operations.filter { it.visibility == OperationVisibility.INTERNAL }.forEach { spec ->
            assertNull("Internal operation ${spec.id} must not appear", FeatureRegistry.get(spec.id))
        }
        assertNull(FeatureRegistry.get("tasks"))
        assertNull(FeatureRegistry.get("task-detail"))
    }

    @Test fun searchIncludesLocalFeatureAndOperationKeywords() {
        assertEquals("github-health", FeatureRegistry.search("ci alerts").single().id)
        assertEquals("notifications", FeatureRegistry.search("audio").single().id)
        assertEquals(FeatureRegistry.features.size, FeatureRegistry.search(" ").size)
    }

    @Test fun stageAHomeKeepsOperationalFunctionsAndAgentOps() {
        assertEquals(
            setOf("system", "agent-ops", "deployments", "github-health", "mcp-access"),
            FeatureRegistry.home.map { it.id }.toSet()
        )
        assertEquals(
            setOf("csms", "benchmark", "notifications", "app-update"),
            FeatureRegistry.secondary.map { it.id }.toSet()
        )
        assertEquals(FeatureGroup.SETTINGS, FeatureRegistry.get("app-update")?.group)
        assertTrue(FeatureRegistry.get("agent-ops")?.operation?.autoExecuteOnOpen == true)
    }

    @Test fun secondaryToolsRemainSearchableAndOpenable() {
        val secondary = FeatureRegistry.secondary.map { it.id }.toSet()
        assertEquals(secondary, FeatureRegistry.visible("", true).map { it.id }.toSet() -
            FeatureRegistry.home.map { it.id }.toSet())
        assertEquals(FeatureRegistry.home.map { it.id }, FeatureRegistry.visible("", false).map { it.id })
        assertEquals("notifications", FeatureRegistry.visible("audio", false).single().id)
        assertEquals("app-update", FeatureRegistry.visible("upgrade", false).single().id)
        for (id in secondary) {
            assertNotNull("Secondary feature must remain addressable: $id", FeatureRegistry.get(id))
        }
        // UI entry is inert until Watchtower advertises real passkey capability.
        assertEquals(FeatureKind.LOCAL_PANEL, FeatureRegistry.get("mcp-access")?.kind)
        assertNull(FeatureRegistry.get("mcp-access")?.operation)
        assertNull(FeatureRegistry.get("bearer"))
    }

    @Test fun localFeaturesCannotClaimBackendOperations() {
        assertTrue(FeatureRegistry.features.filter { it.kind == FeatureKind.LOCAL_PANEL }
            .all { it.operation == null })
        assertTrue(OperationRegistry.operations.none { it.id.startsWith("simulator") })
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsInvalidFeatureIds() {
        FeatureSpec("bad id", "Invalid", "icon", emptySet(), FeatureKind.LOCAL_PANEL)
    }
}
