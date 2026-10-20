package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class AgentSubmissionStatusTest {
    @Test fun actualObservationStatesHaveDistinctLabels() {
        assertEquals("Requested", AgentSubmissionStatus.parse("requested").label)
        assertEquals("Accepted", AgentSubmissionStatus.parse("accepted").label)
        assertEquals("Released", AgentSubmissionStatus.parse("released").label)
        assertEquals("Completed", AgentSubmissionStatus.parse("finished").label)
        assertEquals("Failed", AgentSubmissionStatus.parse("codex_failed").label)
        assertEquals("Interrupted", AgentSubmissionStatus.parse("interrupted").label)
        assertEquals("Report status unknown", AgentSubmissionStatus.parse("reported_unknown").label)
    }

    @Test fun unknownStateCannotBePresentedAsSuccess() {
        assertEquals(AgentSubmissionStatus.UNKNOWN, AgentSubmissionStatus.parse(null))
        assertEquals(AgentSubmissionStatus.UNKNOWN, AgentSubmissionStatus.parse("running"))
        assertFalse(AgentSubmissionStatus.parse("accepted").terminal)
        assertFalse(AgentSubmissionStatus.parse("requested").terminal)
        assertTrue(AgentSubmissionStatus.parse("finished").terminal)
        assertTrue(AgentSubmissionStatus.parse("codex_failed").terminal)
        assertTrue(AgentSubmissionStatus.parse("interrupted").terminal)
    }
}
