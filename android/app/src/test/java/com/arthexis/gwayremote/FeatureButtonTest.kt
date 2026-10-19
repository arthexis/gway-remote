package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class FeatureButtonTest {
    @Test fun allRegisteredFeaturesHaveVectorIcons() {
        FeatureRegistry.features.forEach { feature ->
            assertNotNull(AppIconRegistry.get(feature.icon))
        }
    }

    @Test fun actionMetadataIsPreserved() {
        val feature = FeatureRegistry.get("github-health")!!
        val action = PaletteAction(feature.id, feature.label, feature.icon, {})
        assertEquals("github-health", action.id)
        assertEquals("GitHub Health", action.label)
        assertTrue(action.enabled)
    }
}
