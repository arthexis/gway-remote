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

    @Test fun localFeaturesCannotClaimBackendOperations() {
        assertTrue(FeatureRegistry.features.filter { it.kind == FeatureKind.LOCAL_PANEL }
            .all { it.operation == null })
        assertTrue(OperationRegistry.get("simulator-start")!!.requiresConfirmation)
        assertTrue(OperationRegistry.get("simulator-stop")!!.requiresConfirmation)
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsInvalidFeatureIds() {
        FeatureSpec("bad id", "Invalid", "icon", emptySet(), FeatureKind.LOCAL_PANEL)
    }
}
