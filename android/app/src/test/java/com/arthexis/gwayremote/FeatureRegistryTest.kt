package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class FeatureRegistryTest {
    @Test fun stableIdsAndKnownKinds() {
        val features = FeatureRegistry.features
        assertEquals(features.size, features.map { it.id }.distinct().size)
        assertEquals(OperationRegistry.operations.size + 1, features.size)
        assertEquals(FeatureKind.OPERATION, FeatureRegistry.get("csms")?.kind)
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
        assertEquals("simulator-start",
            FeatureRegistry.get("simulator-start")?.operation?.id)
        assertTrue(FeatureRegistry.get("simulator-start")!!.operation!!.requiresConfirmation)
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsInvalidFeatureIds() {
        FeatureSpec("bad id", "Invalid", "icon", emptySet(), FeatureKind.LOCAL_PANEL)
    }
}
