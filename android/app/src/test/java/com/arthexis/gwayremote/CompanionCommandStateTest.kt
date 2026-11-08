package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class CompanionCommandStateTest {
    @Test fun initialAndBusyLifecyclePreservePreviousOutput() {
        val initial = CompanionCommandState()
        assertEquals("Configure HTTPS endpoint and token", initial.result)
        assertTrue(initial.commands.isEmpty())
        assertFalse(initial.busy)
        val started = initial.listed(listOf("status")).displayed("old").started()
        assertTrue(started.busy)
        assertEquals("old", started.result)
        assertEquals(listOf("status"), started.commands)
        assertFalse(started.completed().busy)
    }

    @Test fun successfulCatalogRequestPreservesOrderAndDuplicates() {
        val result = CompanionCommandState().started()
            .listed(listOf("status", "health", "status")).displayed("response").completed()
        assertEquals(listOf("status", "health", "status"), result.commands)
        assertEquals("response", result.result)
        assertFalse(result.busy)
    }

    @Test fun failedCatalogClearsCommandsButOtherFailuresDoNot() {
        val before = CompanionCommandState(commands = listOf("status"), busy = true)
        assertTrue(before.failed("Connection failed", true).commands.isEmpty())
        val other = before.failed("offline", false)
        assertEquals(listOf("status"), other.commands)
        assertEquals("offline", other.result)
        assertTrue(other.busy)
    }

    @Test fun settingsAndRefreshCanUpdateResultWithoutChangingBusy() {
        val state = CompanionCommandState(commands = listOf("status"))
        assertEquals(listOf("status"), state.displayed("Connection settings saved").commands)
        assertFalse(state.displayed("Invalid settings").busy)
    }

    @Test fun refreshSummaryPreservesFailureOrderAndMessages() {
        assertEquals("Refresh completed", CompanionRefreshSummary.message(emptyList()))
        assertEquals("Refresh partially failed: API settings: bad; Commands: offline; App update: timeout",
            CompanionRefreshSummary.message(listOf("API settings: bad", "Commands: offline", "App update: timeout")))
    }
}
