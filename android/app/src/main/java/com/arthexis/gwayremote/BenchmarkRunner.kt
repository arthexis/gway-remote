package com.arthexis.gwayremote

import android.os.SystemClock
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.util.UUID
import kotlin.math.ceil

data class BenchmarkConfig(val samples: Int = 100, val warmup: Int = 5,
                           val timeoutMs: Int = 5000, val payloadBytes: Int = 0) {
    init {
        require(samples in 1..1000 && warmup in 0..100 && timeoutMs in 1000..30000 &&
                payloadBytes in 0..4096) { "Benchmark parameters out of range" }
    }
}

enum class BenchmarkMode { ECHO, STATUS, BOTH }

data class BenchmarkResult(val rttNs: List<Long>, val processingNs: List<Long>,
                           val failures: Int, val attempted: Int, val cancelled: Boolean,
                           val command: String = "benchmark-echo",
                           val executionNs: List<Long> = emptyList()) {
    fun summary(values: List<Long>): String {
        if (values.isEmpty()) return "No successful samples"
        val sorted = values.sorted()
        fun ms(ns: Double) = "%.2f".format(java.util.Locale.US, ns / 1_000_000.0)
        return "median ${ms((sorted[(sorted.size - 1) / 2].toDouble() + sorted[sorted.size / 2]) / 2)} ms · " +
            "p95 ${ms(sorted[ceil(.95 * sorted.size).toInt() - 1].toDouble())} ms · " +
            "min ${ms(sorted.first().toDouble())} ms · max ${ms(sorted.last().toDouble())} ms"
    }

    fun json(): JSONObject = JSONObject()
        .put("command", command).put("attempted", attempted).put("failures", failures)
        .put("cancelled", cancelled).put("rtt_ns", JSONArray(rttNs))
        .put("echo_processing_ns", JSONArray(processingNs))
        .put("api_execution_ns", JSONArray(executionNs))
}

data class BenchmarkReport(val runId: String, val timestamp: String, val connectionLabel: String,
                           val node: String, val config: BenchmarkConfig, val mode: BenchmarkMode,
                           val results: List<BenchmarkResult>, val appVersion: String) {
    fun json(): JSONObject = JSONObject()
        .put("schema", "gway-remote-benchmark/v1").put("run_id", runId)
        .put("timestamp", timestamp).put("connection_label", connectionLabel)
        .put("node", node).put("app_version", appVersion)
        .put("mode", mode.name.lowercase())
        .put("samples", config.samples).put("warmup", config.warmup)
        .put("timeout_ms", config.timeoutMs).put("payload_bytes", config.payloadBytes)
        .put("results", JSONArray().also { array -> results.forEach { array.put(it.json()) } })

    fun markdown(): String = buildString {
        appendLine("### GWAY Remote benchmark — $runId")
        appendLine()
        appendLine("- Timestamp: $timestamp")
        appendLine("- Node: $node")
        appendLine("- Connection label: $connectionLabel")
        appendLine("- App version: $appVersion")
        appendLine("- Mode: ${mode.name}; samples: ${config.samples}; warmup: ${config.warmup}")
        for (result in results) {
            appendLine()
            appendLine("**${result.command}** — ${result.rttNs.size}/${result.attempted} successful, " +
                       "${result.failures} failures${if (result.cancelled) ", cancelled" else ""}")
            appendLine("- Phone RTT: ${result.summary(result.rttNs)}")
            if (result.processingNs.isNotEmpty())
                appendLine("- Pi echo processing: ${result.summary(result.processingNs)}")
            if (result.executionNs.isNotEmpty())
                appendLine("- Pi API execution: ${result.summary(result.executionNs)}")
        }
        appendLine()
        appendLine("<details><summary>Raw benchmark JSON</summary>")
        appendLine()
        appendLine("```json")
        appendLine(json().toString(2))
        appendLine("```")
        appendLine("</details>")
    }

    companion object {
        fun create(label: String, node: String, config: BenchmarkConfig,
                   mode: BenchmarkMode, results: List<BenchmarkResult>, version: String) =
            BenchmarkReport(UUID.randomUUID().toString(), Instant.now().toString(),
                label.take(64), node.take(128), config, mode, results, version)
    }
}

class BenchmarkRunner(private val request: (String, JSONObject, Int) -> JSONObject) {
    suspend fun run(config: BenchmarkConfig, command: String, shouldStop: () -> Boolean,
                    progress: (Int, Int) -> Unit): BenchmarkResult = withContext(Dispatchers.IO) {
        require(command == "benchmark-echo" || command == "status")
        val rtts = mutableListOf<Long>()
        val processing = mutableListOf<Long>()
        val executions = mutableListOf<Long>()
        var failures = 0
        var attempted = 0
        var cancelled = false
        val args = if (command == "benchmark-echo")
            JSONObject().put("payload", "x".repeat(config.payloadBytes)) else JSONObject()
        for (index in 0 until config.warmup + config.samples) {
            if (shouldStop()) { cancelled = true; break }
            val start = SystemClock.elapsedRealtimeNanos()
            try {
                val response = request(command, args, config.timeoutMs)
                val elapsed = SystemClock.elapsedRealtimeNanos() - start
                val result = response.getJSONObject("result")
                if (command == "benchmark-echo") {
                    if (result.getString("payload") != args.getString("payload"))
                        error("Echo payload mismatch")
                }
                val execution = response.optLong("execution_ns", -1)
                val echo = if (command == "benchmark-echo") result.getLong("processing_ns") else -1
                if (execution < -1 || echo < -1) error("Invalid server timing")
                if (index >= config.warmup) {
                    rtts.add(elapsed)
                    if (echo >= 0) processing.add(echo)
                    if (execution >= 0) executions.add(execution)
                }
            } catch (e: Exception) {
                if (index >= config.warmup) failures++
            }
            if (index >= config.warmup) {
                attempted++
                withContext(Dispatchers.Main) { progress(attempted, config.samples) }
            }
        }
        BenchmarkResult(rtts, processing, failures, attempted, cancelled, command, executions)
    }
}
