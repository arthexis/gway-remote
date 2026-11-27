package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

/** No network or Android framework calls: verify the package-id security boundary. */
class AppUpdateChannelTest {
    @Test fun stableReleasesAreOnlyForProductionPackage() {
        assertTrue(AppUpdateChannel.supportsStableUpdates("com.arthexis.gwayremote"))
        assertFalse(AppUpdateChannel.supportsStableUpdates("com.arthexis.gwayremote.canary"))
        assertFalse(AppUpdateChannel.supportsStableUpdates("com.arthexis.gwayremote.canary.test"))
        assertFalse(AppUpdateChannel.supportsStableUpdates("com.arthexis.gwayremote.debug"))
        assertFalse(AppUpdateChannel.supportsStableUpdates(""))
    }

    @Test fun canaryCannotReachStableUpdaterOperations() {
        val exception = assertThrows(IllegalArgumentException::class.java) {
            AppUpdateChannel.requireStableUpdates("com.arthexis.gwayremote.canary")
        }
        assertEquals(AppUpdateChannel.CANARY_NOTICE, exception.message)
        AppUpdateChannel.requireStableUpdates("com.arthexis.gwayremote")
    }
}
