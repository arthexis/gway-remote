package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class OperationExecutorTest {
    @Test fun automaticRequestsAreAllowlisted() {
        assertEquals("/api/v1/health", OperationRequests.automatic("api-health")?.path)
        assertEquals("status-quick", OperationRequests.automatic("status")?.command)
        assertNull(OperationRequests.automatic("sound"))
        assertNull(OperationRequests.automatic("arbitrary-shell"))
        assertNull(OperationRequests.automatic("agent-ops"))
    }

    @Test fun explicitInputsAreValidatedAndPreservePayloads() {
        assertNull(OperationRequests.explicit("task-detail", mapOf("task_id" to "bogus")))
        assertEquals("sound-play", OperationRequests.explicit("sound",
            mapOf("sound" to "notice", "motif" to "start"))?.command)
    }

    @Test fun confirmationPolicyCannotBeBypassed() {
        assertNull(OperationRequests.explicit("unknown", emptyMap()))
        assertNull(OperationRequests.explicit("status", emptyMap()))
    }

    @Test fun reducerRejectsClosedAndStaleResponses() {
        val state = PanelRunState(OperationPanelState().open("status").state)
        val old = state.start("status")!!
        state.update(state.current.close("status").open("status").state)
        val current = state.start("status")!!
        state.complete("status", old, "old")
        assertTrue(state.current.panels.single().loading)
        state.complete("status", current, "fresh")
        assertEquals("fresh", state.current.panels.single().output)
    }
}
