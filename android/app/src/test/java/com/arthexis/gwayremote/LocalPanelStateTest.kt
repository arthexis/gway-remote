package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class LocalPanelStateTest {
    @Test fun localPanelsOpenCloseAndReorder() {
        val opened = LocalPanelState().open("deployments").open("github-health")
        assertEquals(listOf("github-health", "deployments"), opened.openIds)
        assertEquals(listOf("deployments", "github-health"),
            opened.move("deployments", 0).openIds)
        assertEquals(listOf("github-health"), opened.close("deployments").openIds)
        assertEquals(opened, opened.open("github-health"))
    }

    @Test fun updateActionIsNotAPanel() {
        assertFalse(LocalPanelState.isPanel("app-update"))
        assertTrue(LocalPanelState.isPanel("deployments"))
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsUnknownPanel() {
        LocalPanelState().open("not-registered")
    }
}
