package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class CompanionActivityStateTest {
    @Test fun refreshTransitionsPreserveExactMessages() {
        val initial = CompanionRefreshState()
        assertFalse(initial.running)
        assertEquals("", initial.status)
        val started = initial.started()
        assertTrue(started.running)
        assertEquals("Refreshing…", started.status)
        assertEquals(CompanionRefreshState(false, "Refresh completed"), started.finished("Refresh completed"))
        assertEquals(CompanionRefreshState(false, "Refresh partially failed: API settings: offline"),
            started.finished("Refresh partially failed: API settings: offline"))
    }

    @Test fun updateTransitionsKeepStatusAndBusyIndependent() {
        val initial = CompanionUpdateState()
        val checking = initial.started("Checking releases…")
        assertTrue(checking.running)
        assertEquals("Checking releases…", checking.status)
        val found = checking.status("Update available: 2.0")
        assertTrue(found.running)
        assertEquals("Update available: 2.0", found.finished().status)
        assertFalse(found.finished().running)
        assertEquals(initial, CompanionUpdateState())
    }

    @Test fun updateErrorCanBeReportedWithoutMarkingBusy() {
        assertEquals(CompanionUpdateState(false, "Update check failed"),
            CompanionUpdateState().status("Update check failed"))
    }
}
