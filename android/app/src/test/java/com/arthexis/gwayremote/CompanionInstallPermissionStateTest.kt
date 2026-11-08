package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class CompanionInstallPermissionStateTest {
    @Test fun initialStateIgnoresUnsolicitedActivityResult() {
        val state = CompanionInstallPermissionState()
        val result = state.result(true)
        assertFalse(result.launchInstaller)
        assertNull(result.status)
        assertEquals(state, result.state)
    }

    @Test fun requestAndGrantLaunchExactlyOnce() {
        val waiting = CompanionInstallPermissionState().requested()
        assertTrue(waiting.awaitingResult)
        val granted = waiting.result(true)
        assertTrue(granted.launchInstaller)
        assertNull(granted.status)
        assertFalse(granted.state.awaitingResult)
        assertFalse(granted.state.result(true).launchInstaller)
    }

    @Test fun denialPreservesOriginalMessageAndClearsWait() {
        val result = CompanionInstallPermissionState().requested().result(false)
        assertFalse(result.launchInstaller)
        assertEquals("Installation permission not granted; allow installs from GWay Remote", result.status)
        assertFalse(result.state.awaitingResult)
    }

    @Test fun launcherFailurePreservesMessageAndClearsWait() {
        val result = CompanionInstallPermissionState().requested().launchFailed("blocked")
        assertFalse(result.launchInstaller)
        assertEquals("Unable to open installation settings: blocked", result.status)
        assertFalse(result.state.awaitingResult)
    }

    @Test fun nullLauncherErrorRetainsStringInterpolation() {
        val result = CompanionInstallPermissionState().requested().launchFailed(null)
        assertEquals("Unable to open installation settings: null", result.status)
        assertFalse(result.launchInstaller)
    }

    @Test fun requestCanBeRepeatedAfterDenial() {
        val denied = CompanionInstallPermissionState().requested().result(false)
        assertTrue(denied.state.requested().result(true).launchInstaller)
    }
}
