package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class CompanionBenchmarkLifecycleTest {
    @Test fun startResetsPreviousErrorAndProgress() {
        val before = CompanionBenchmarkLifecycle(progress = 42, error = "offline")
        val after = before.started()
        assertTrue(after.running)
        assertEquals(0, after.progress)
        assertEquals("", after.error)
        assertNull(after.report)
        assertEquals(42, before.progress)
    }

    @Test fun progressDoesNotAlterRunningOrError() {
        val started = CompanionBenchmarkLifecycle().started()
        val next = started.progressed(7)
        assertEquals(7, next.progress)
        assertTrue(next.running)
        assertEquals("", next.error)
    }

    @Test fun failureRemainsVisibleAfterFinally() {
        val finished = CompanionBenchmarkLifecycle().started().failed("offline").finished()
        assertFalse(finished.running)
        assertEquals("offline", finished.error)
        assertNull(finished.report)
    }

    @Test fun failedValidationDoesNotStartExecution() {
        val invalid = CompanionBenchmarkLifecycle().failed("Invalid parameters")
        assertFalse(invalid.running)
        assertEquals("Invalid parameters", invalid.error)
    }

    @Test fun finishPreservesProgress() {
        val done = CompanionBenchmarkLifecycle().started().progressed(100).finished()
        assertFalse(done.running)
        assertEquals(100, done.progress)
    }
}
