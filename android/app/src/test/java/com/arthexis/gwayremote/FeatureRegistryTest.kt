package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class FeatureRegistryTest {
    @Test fun stableIdsAndKnownKinds() {
        val features = FeatureRegistry.features
        assertEquals(features.size, features.map { it.id }.distinct().size)
        assertEquals(OperationRegistry.operations.size - 6 + 3, features.size)
        assertEquals(FeatureKind.LOCAL_PANEL, FeatureRegistry.get("app-update")?.kind)
        assertEquals(FeatureKind.LOCAL_PANEL, FeatureRegistry.get("legacy-assignments")?.kind)
        assertEquals(FeatureKind.OPERATION, FeatureRegistry.get("csms")?.kind)
        assertNull(FeatureRegistry.get("csms-view"))
        assertEquals(FeatureKind.OPERATION, FeatureRegistry.get("simulator")?.kind)
        assertNull(FeatureRegistry.get("simulator-start"))
        assertNull(FeatureRegistry.get("simulator-status"))
        assertEquals(FeatureKind.LOCAL_PANEL, FeatureRegistry.get("github-health")?.kind)
        assertNull(FeatureRegistry.get("github-health")?.operation)
        assertNull(FeatureRegistry.get("arbitrary-shell"))
    }

    @Test fun searchIncludesLocalFeatureAndOperationKeywords() {
        assertEquals("github-health", FeatureRegistry.search("ci alerts").single().id)
        assertEquals("sound", FeatureRegistry.search("audio").single().id)
        assertEquals(FeatureRegistry.features.size, FeatureRegistry.search(" ").size)
    }

    @Test fun localFeaturesCannotClaimBackendOperations() {
        assertTrue(FeatureRegistry.features.filter { it.kind == FeatureKind.LOCAL_PANEL }
            .all { it.operation == null })
        assertNull(FeatureRegistry.get("simulator-start"))
        assertEquals("simulator", FeatureRegistry.get("simulator")?.operation?.id)
        assertTrue(OperationRegistry.get("simulator-start")!!.requiresConfirmation)
        assertTrue(OperationRegistry.get("simulator-stop")!!.requiresConfirmation)
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsInvalidFeatureIds() {
        FeatureSpec("bad id", "Invalid", "icon", emptySet(), FeatureKind.LOCAL_PANEL)
    }
}
