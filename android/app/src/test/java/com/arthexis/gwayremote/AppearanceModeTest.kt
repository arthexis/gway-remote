package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class AppearanceModeTest {
    @Test fun systemFollowsAndroidNightMode() {
        assertTrue(AppearanceMode.SYSTEM.isDark(true))
        assertFalse(AppearanceMode.SYSTEM.isDark(false))
    }

    @Test fun manualModesOverrideAndroid() {
        assertTrue(AppearanceMode.DARK.isDark(false))
        assertFalse(AppearanceMode.LIGHT.isDark(true))
    }

    @Test fun preferenceDefaultsSafelyToSystem() {
        assertEquals(AppearanceMode.SYSTEM, AppearanceMode.fromStored(null))
        assertEquals(AppearanceMode.SYSTEM, AppearanceMode.fromStored("unknown"))
        assertEquals(AppearanceMode.DARK, AppearanceMode.fromStored("DARK"))
        assertEquals(AppearanceMode.LIGHT, AppearanceMode.fromStored("LIGHT"))
    }
}
