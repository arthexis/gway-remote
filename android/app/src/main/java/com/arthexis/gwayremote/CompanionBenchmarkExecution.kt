package com.arthexis.gwayremote

/**
 * Executes the selected benchmark commands in their original order.
 * Caller owns the stop flag, coroutine lifecycle, report and error state.
 */
internal object CompanionBenchmarkExecution {
    suspend fun run(
        config: BenchmarkConfig,
        commands: List<String>,
        cancelled: () -> Boolean,
        runner: suspend (String, (Int) -> Unit) -> BenchmarkResult,
        progress: (Int) -> Unit
    ): List<BenchmarkResult> {
        val results = mutableListOf<BenchmarkResult>()
        for ((index, command) in commands.withIndex()) {
            if (cancelled()) break
            results.add(runner(command) { completed ->
                progress(index * config.samples + completed)
            })
        }
        return results
    }
}
