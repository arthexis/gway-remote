package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class ReadPanelParityTest {
    @Test fun apiReadsHaveStableIdsAndSafePolicy() {
        for (id in listOf("api-health", "api-commands")) {
            val spec = OperationRegistry.get(id)!!
            assertEquals(ExecutionPolicy.AUTO_READ, spec.policy)
            assertTrue(OperationPanelState().open(id).shouldAutoRun)
        }
    }

    @Test fun readPanelsDoNotAffectEachOther() {
        var state = OperationPanelState().open("api-health").state.open("api-commands").state
        state = state.start("api-health")
        val revision = state.panels.first { it.id == "api-health" }.revision
        state = state.complete("api-health", revision, "healthy")
        assertEquals("healthy", state.panels.first { it.id == "api-health" }.output)
        assertNull(state.panels.first { it.id == "api-commands" }.output)
    }
}
