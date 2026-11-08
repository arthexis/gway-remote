package com.arthexis.gwayremote

/**
 * Immutable UI lifecycle snapshot. Cancellation ownership stays with the existing
 * AtomicBoolean; network, coroutine scope and report construction stay in the screen.
 */
internal data class CompanionBenchmarkLifecycle(
    val running: Boolean = false,
    val progress: Int = 0,
    val report: BenchmarkReport? = null,
    val error: String = ""
) {
    fun started() = copy(running = true, progress = 0, report = null, error = "")
    fun progressed(value: Int) = copy(progress = value)
    fun succeeded(value: BenchmarkReport) = copy(report = value)
    fun failed(message: String) = copy(error = message)
    fun finished() = copy(running = false)
}
