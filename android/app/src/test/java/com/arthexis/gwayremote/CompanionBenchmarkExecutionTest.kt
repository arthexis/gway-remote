package com.arthexis.gwayremote

import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class CompanionBenchmarkExecutionTest {
    private fun result(command: String) = BenchmarkResult(
        rttNs = emptyList(), processingNs = emptyList(), failures = 0,
        attempted = 0, cancelled = false, command = command
    )

    @Test fun orderedCommandsAndCumulativeProgress() = runBlocking {
        val visited = mutableListOf<String>()
        val progress = mutableListOf<Int>()
        val output = CompanionBenchmarkExecution.run(
            BenchmarkConfig(samples = 10), listOf("benchmark-echo", "status"),
            { false },
            { command, onProgress ->
                visited.add(command)
                onProgress(3)
                onProgress(10)
                result(command)
            },
            { progress.add(it) }
        )
        assertEquals(listOf("benchmark-echo", "status"), visited)
        assertEquals(listOf(3, 10, 13, 20), progress)
        assertEquals(visited, output.map { it.command })
    }

    @Test fun cancellationBeforeStartSkipsAllCommands() = runBlocking {
        var invoked = false
        val output = CompanionBenchmarkExecution.run(
            BenchmarkConfig(), listOf("benchmark-echo"), { true },
            { command, _ -> invoked = true; result(command) }, {}
        )
        assertFalse(invoked)
        assertTrue(output.isEmpty())
    }

    @Test fun cancellationBetweenCommandsRetainsPartialResults() = runBlocking {
        var stopped = false
        val output = CompanionBenchmarkExecution.run(
            BenchmarkConfig(), listOf("benchmark-echo", "status"), { stopped },
            { command, _ -> stopped = true; result(command) }, {}
        )
        assertEquals(listOf("benchmark-echo"), output.map { it.command })
    }

    @Test fun runnerFailurePropagatesToCaller() = runBlocking {
        try {
            CompanionBenchmarkExecution.run(
                BenchmarkConfig(), listOf("status"), { false },
                { _, _ -> error("offline") }, {}
            )
            fail("Expected failure")
        } catch (e: IllegalStateException) {
            assertEquals("offline", e.message)
        }
    }
}
