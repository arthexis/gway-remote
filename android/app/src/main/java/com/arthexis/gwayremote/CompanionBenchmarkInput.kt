package com.arthexis.gwayremote

/** Editable inputs only; benchmark execution and cancellation stay in the screen. */
internal data class CompanionBenchmarkInput(
    val samples: String = "100",
    val warmup: String = "5",
    val timeout: String = "5",
    val payload: String = "0",
    val mode: BenchmarkMode = BenchmarkMode.BOTH,
    val label: String = "Unspecified"
) {
    fun config() = BenchmarkConfig(
        samples = samples.toInt(),
        warmup = warmup.toInt(),
        timeoutMs = timeout.toInt() * 1000,
        payloadBytes = payload.toInt()
    )

    fun commands(): List<String> =
        if (mode == BenchmarkMode.BOTH) listOf("benchmark-echo", "status")
        else listOf(if (mode == BenchmarkMode.ECHO) "benchmark-echo" else "status")
}
