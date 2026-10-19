package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class FeatureRegistryTest {
    @Test fun stableIdsAndKnownKinds() {
        val features = FeatureRegistry.features
        assertEquals(features.size, features.map { it.id }.distinct().size)
        assertEquals(OperationRegistry.operations.count { it.visibility == OperationVisibility.PALETTE } +
            features.count { it.kind == FeatureKind.LOCAL_PANEL }, features.size)
        assertEquals(FeatureKind.LOCAL_PANEL, FeatureRegistry.get("app-update")?.kind)
        assertNull(FeatureRegistry.get("legacy-assignments"))
        assertEquals(FeatureKind.OPERATION, FeatureRegistry.get("csms")?.kind)
        assertEquals(FeatureKind.OPERATION, FeatureRegistry.get("tasks")?.kind)
        assertEquals(FeatureKind.OPERATION, FeatureRegistry.get("simulator")?.kind)
        assertEquals(FeatureKind.LOCAL_PANEL, FeatureRegistry.get("github-health")?.kind)
        assertNull(FeatureRegistry.get("github-health")?.operation)
        assertNull(FeatureRegistry.get("arbitrary-shell"))
    }

    @Test fun unifiedPanelsHideInternalActionsWithoutRemovingBackendContracts() {
        val hidden = listOf("simulator-status", "simulator-discover", "simulator-start",
            "simulator-stop", "simulator-results", "csms-view", "task-detail", "agent-assignments")
        hidden.forEach { id ->
            assertNull("Internal operation $id must not appear in the palette", FeatureRegistry.get(id))
            assertNotNull("Backend contract $id must remain registered", OperationRegistry.get(id))
            assertEquals(OperationVisibility.INTERNAL, OperationRegistry.get(id)?.visibility)
        }
        listOf("simulator", "csms", "tasks", "agent-ops").forEach { id ->
            assertNotNull(FeatureRegistry.get(id))
        }
        assertTrue(FeatureRegistry.features.none { it.id in hidden })
        assertEquals(OperationRegistry.operations.filter { it.visibility == OperationVisibility.PALETTE }.map { it.id }.toSet(),
            FeatureRegistry.features.filter { it.kind == FeatureKind.OPERATION }.map { it.id }.toSet())
    }

    @Test fun searchIncludesLocalFeatureAndOperationKeywords() {
        assertEquals("github-health", FeatureRegistry.search("ci alerts").single().id)
        assertEquals("sound", FeatureRegistry.search("audio").single().id)
        assertEquals(FeatureRegistry.features.size, FeatureRegistry.search(" ").size)
    }

    @Test fun localFeaturesCannotClaimBackendOperations() {
        assertTrue(FeatureRegistry.features.filter { it.kind == FeatureKind.LOCAL_PANEL }
            .all { it.operation == null })
        assertEquals("simulator", FeatureRegistry.get("simulator")?.operation?.id)
        assertTrue(OperationRegistry.get("simulator-start")!!.requiresConfirmation)
        assertTrue(OperationRegistry.get("simulator-stop")!!.requiresConfirmation)
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsInvalidFeatureIds() {
        FeatureSpec("bad id", "Invalid", "icon", emptySet(), FeatureKind.LOCAL_PANEL)
    }
}
