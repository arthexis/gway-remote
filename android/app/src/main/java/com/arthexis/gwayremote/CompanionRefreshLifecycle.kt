package com.arthexis.gwayremote

/**
 * UI refresh lifecycle boundary. The caller retains the coroutine scope,
 * request order, cancellation and all side effects.
 */
internal object CompanionRefreshLifecycle {
    fun canStart(
        refreshing: Boolean,
        commandBusy: Boolean,
        benchmarkRunning: Boolean,
        updating: Boolean
    ): Boolean = !refreshing && !commandBusy && !benchmarkRunning && !updating

    suspend fun run(
        work: suspend (MutableList<String>) -> Unit,
        onSummary: (String) -> Unit,
        onFinished: () -> Unit
    ) {
        val failures = mutableListOf<String>()
        try {
            work(failures)
            onSummary(CompanionRefreshSummary.message(failures))
        } finally {
            onFinished()
        }
    }
}
