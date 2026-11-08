package com.arthexis.gwayremote

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class CompanionRefreshLifecycleTest {
    @Test fun guardRejectsEachConflictingOperation() {
        assertTrue(CompanionRefreshLifecycle.canStart(false, false, false, false))
        assertFalse(CompanionRefreshLifecycle.canStart(true, false, false, false))
        assertFalse(CompanionRefreshLifecycle.canStart(false, true, false, false))
        assertFalse(CompanionRefreshLifecycle.canStart(false, false, true, false))
        assertFalse(CompanionRefreshLifecycle.canStart(false, false, false, true))
    }

    @Test fun successfulRefreshSummarizesThenFinishes() = runBlocking {
        val events = mutableListOf<String>()
        CompanionRefreshLifecycle.run(
            { events.add("work") },
            { events.add(it) },
            { events.add("finished") }
        )
        assertEquals(listOf("work", "Refresh completed", "finished"), events)
    }

    @Test fun partialFailuresRetainOrderAndFinish() = runBlocking {
        val events = mutableListOf<String>()
        CompanionRefreshLifecycle.run(
            { failures -> failures.add("Health: offline"); failures.add("App update: timeout") },
            { events.add(it) },
            { events.add("finished") }
        )
        assertEquals(listOf("Refresh partially failed: Health: offline; App update: timeout", "finished"), events)
    }

    @Test fun unexpectedExceptionSkipsSummaryButAlwaysFinishes() = runBlocking {
        val events = mutableListOf<String>()
        try {
            CompanionRefreshLifecycle.run(
                { throw IllegalStateException("bad JSON") },
                { events.add("summary") },
                { events.add("finished") }
            )
            fail("Expected exception")
        } catch (e: IllegalStateException) {
            assertEquals("bad JSON", e.message)
        }
        assertEquals(listOf("finished"), events)
    }

    @Test fun cancellationPropagatesAndAlwaysFinishes() = runBlocking {
        val events = mutableListOf<String>()
        try {
            CompanionRefreshLifecycle.run(
                { throw CancellationException("cancelled") },
                { events.add("summary") },
                { events.add("finished") }
            )
            fail("Expected cancellation")
        } catch (e: CancellationException) {
            assertEquals("cancelled", e.message)
        }
        assertEquals(listOf("finished"), events)
    }
}
