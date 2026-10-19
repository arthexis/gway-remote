package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class ReadPanelParityTest {
    @Test fun apiHealthRetainsSafeReadPolicy() {
        val spec = OperationRegistry.get("api-health")!!
        assertEquals(ExecutionPolicy.AUTO_READ, spec.policy)
        assertTrue(OperationPanelState().open("api-health").shouldAutoRun)
    }

    @Test fun redundantCommandsPanelIsNotRegistered() {
        assertNull(OperationRegistry.get("api-commands"))
        assertTrue(FeatureRegistry.search("Available commands").isEmpty())
    }

    @Test fun apiHealthStateIsIndependentOfOtherReadPanels() {
        var state = OperationPanelState().open("api-health").state.open("status").state
        state = state.start("api-health")
        val revision = state.panels.first { it.id == "api-health" }.revision
        state = state.complete("api-health", revision, "healthy")
        assertEquals("healthy", state.panels.first { it.id == "api-health" }.output)
        assertNull(state.panels.first { it.id == "status" }.output)
    }
}
