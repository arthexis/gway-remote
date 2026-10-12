package com.arthexis.gwayremote

import android.os.SystemClock
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import org.json.JSONObject
import kotlin.coroutines.coroutineContext
import kotlin.math.ceil

data class BenchmarkConfig(val samples: Int = 100, val warmup: Int = 5,
                           val timeoutMs: Int = 5000, val payloadBytes: Int = 0) {
    init {
        require(samples in 1..1000 && warmup in 0..100 && timeoutMs in 1000..30000 &&
                payloadBytes in 0..4096) { "Benchmark parameters out of range" }
    }
}

data class BenchmarkResult(val rttNs: List<Long>, val processingNs: List<Long>,
                           val failures: Int, val attempted: Int, val cancelled: Boolean) {
    fun summary(values: List<Long>): String {
        if (values.isEmpty()) return "No successful samples"
        val sorted = values.sorted()
        fun ms(ns: Double) = "%.2f".format(java.util.Locale.US, ns / 1_000_000.0)
        return "median ${ms((sorted[(sorted.size - 1) / 2].toDouble() + sorted[sorted.size / 2]) / 2)} ms · " +
            "p95 ${ms(sorted[ceil(.95 * sorted.size).toInt() - 1].toDouble())} ms · " +
            "min ${ms(sorted.first().toDouble())} ms · max ${ms(sorted.last().toDouble())} ms"
    }
}

class BenchmarkRunner(private val request: (String, Int) -> JSONObject = { payload, timeout ->
    throw UnsupportedOperationException("Provide authenticated request transport")
}) {
    suspend fun run(config: BenchmarkConfig, progress: (Int, Int) -> Unit): BenchmarkResult =
        withContext(Dispatchers.IO) {
            val rtts = mutableListOf<Long>()
            val server = mutableListOf<Long>()
            var failures = 0
            var attempted = 0
            var cancelled = false
            val payload = "x".repeat(config.payloadBytes)
            try {
                repeat(config.warmup + config.samples) { index ->
                    coroutineContext.ensureActive()
                    val start = SystemClock.elapsedRealtimeNanos()
                    try {
                        val result = request(payload, config.timeoutMs).getJSONObject("result")
                        val elapsed = SystemClock.elapsedRealtimeNanos() - start
                        if (result.getString("payload") != payload) error("Echo payload mismatch")
                        val processing = result.getLong("processing_ns")
                        if (processing < 0) error("Invalid server timing")
                        if (index >= config.warmup) {
                            rtts.add(elapsed)
                            server.add(processing)
                        }
                    } catch (e: CancellationException) {
                        throw e
                    } catch (e: Exception) {
                        if (index >= config.warmup) failures++
                    }
                    if (index >= config.warmup) {
                        attempted++
                        withContext(Dispatchers.Main) { progress(attempted, config.samples) }
                    }
                }
            } catch (_: CancellationException) {
                cancelled = true
            }
            BenchmarkResult(rtts, server, failures, attempted, cancelled)
        }
}
