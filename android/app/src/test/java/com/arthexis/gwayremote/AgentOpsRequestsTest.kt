package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class AgentOpsRequestsTest {
    @Test fun onlyReviewedCommandsAreExposed() {
        assertEquals("agent-observe", AgentOpsRequests.observe("owner/repo#12", "now").command)
        assertEquals("agent-preview", AgentOpsRequests.preview("owner/repo#12").command)
        assertEquals("agent-issue", AgentOpsRequests.send("owner/repo#12", "now").command)
        assertEquals("agent-issues", AgentOpsRequests.assignments().command)
        assertEquals("/api/v1/execute", AgentOpsRequests.assignments().path)
    }

    @Test fun requestsKeepArgumentsSeparateAndTyped() {
        assertEquals(mapOf("ref" to "owner/repo#12", "at" to "now"),
            AgentOpsRequests.observe("owner/repo#12", "now").parameters)
        assertEquals(mapOf("ref" to "owner/repo#12"),
            AgentOpsRequests.preview("owner/repo#12").parameters)
        assertTrue(AgentOpsRequests.assignments().parameters.isEmpty())
    }

    @Test fun viewModelInitialStateIsIdle() {
        val model = AgentOpsViewModel()
        assertFalse(model.sendLoading)
        assertFalse(model.observeLoading)
        assertFalse(model.issuesLoading)
        assertTrue(model.issues.isEmpty())
        assertNull(model.sendResult)
        assertNull(model.observeError)
    }
}
