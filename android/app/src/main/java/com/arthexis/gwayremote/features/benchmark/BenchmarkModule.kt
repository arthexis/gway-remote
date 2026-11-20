package com.arthexis.gwayremote.features.benchmark

import com.arthexis.gwayremote.*
import com.arthexis.gwayremote.ui.components.ModuleHeader
import com.arthexis.gwayremote.ui.components.ModuleLoading
import com.arthexis.gwayremote.ui.components.ModuleNotice
import com.arthexis.gwayremote.ui.components.ModuleActions
import com.arthexis.gwayremote.ui.components.ModuleSectionTitle

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch

/** Benchmark owns its input, cancellation and results independently of navigation. */
@Composable
internal fun BenchmarkModule(endpoint: String, token: String) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var benchmarkInput by remember { mutableStateOf(CompanionBenchmarkInput()) }
    val benchmarkSamples = benchmarkInput.samples
    val benchmarkWarmup = benchmarkInput.warmup
    val benchmarkTimeout = benchmarkInput.timeout
    val benchmarkPayload = benchmarkInput.payload
    val benchmarkMode = benchmarkInput.mode
    val benchmarkLabel = benchmarkInput.label
    var benchmarkLifecycle by remember { mutableStateOf(CompanionBenchmarkLifecycle()) }
    val benchmarkProgress = benchmarkLifecycle.progress
    val benchmarkRunning = benchmarkLifecycle.running
    val benchmarkReport = benchmarkLifecycle.report
    val benchmarkError = benchmarkLifecycle.error
    val benchmarkStop = remember { java.util.concurrent.atomic.AtomicBoolean(false) }
    DisposableEffect(Unit) { onDispose { benchmarkStop.set(true) } }

        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            ModuleHeader("Benchmark", "Authenticated echo and read-only status · connected node")
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                for (mode in BenchmarkMode.entries) {
                    FilterChip(selected = benchmarkMode == mode, onClick = { benchmarkInput = benchmarkInput.copy(mode = mode) },
                        label = { Text(mode.name.lowercase().replaceFirstChar { it.uppercase() }) })
                }
            }
            OutlinedTextField(benchmarkLabel, { benchmarkInput = benchmarkInput.copy(label = it) }, label = { Text("Connection label (AP / LAN / remote)") },
                modifier = Modifier.fillMaxWidth(), singleLine = true)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(benchmarkSamples, { benchmarkInput = benchmarkInput.copy(samples = it) }, label = { Text("Samples") },
                    modifier = Modifier.weight(1f), singleLine = true)
                OutlinedTextField(benchmarkWarmup, { benchmarkInput = benchmarkInput.copy(warmup = it) }, label = { Text("Warmup") },
                    modifier = Modifier.weight(1f), singleLine = true)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(benchmarkTimeout, { benchmarkInput = benchmarkInput.copy(timeout = it) }, label = { Text("Timeout (s)") },
                    modifier = Modifier.weight(1f), singleLine = true)
                OutlinedTextField(benchmarkPayload, { benchmarkInput = benchmarkInput.copy(payload = it) }, label = { Text("Payload (bytes)") },
                    modifier = Modifier.weight(1f), singleLine = true)
            }
            if (benchmarkRunning) {
                Text("Progress: $benchmarkProgress / ${(benchmarkSamples.toIntOrNull() ?: 0) * (if (benchmarkMode == BenchmarkMode.BOTH) 2 else 1)}")
                LinearProgressIndicator(
                    progress = { benchmarkProgress.toFloat() / ((benchmarkSamples.toIntOrNull()?.coerceAtLeast(1) ?: 1) * (if (benchmarkMode == BenchmarkMode.BOTH) 2 else 1)) },
                    modifier = Modifier.fillMaxWidth()
                )
            }
            ModuleActions {
                Button(enabled = !benchmarkRunning, onClick = {
                    try {
                        val config = benchmarkInput.config()
                        benchmarkLifecycle = benchmarkLifecycle.started()
                        benchmarkStop.set(false)
                        val targetEndpoint = endpoint.trim()
                        val targetToken = token
                        scope.launch {
                            try {
                                val runner = BenchmarkRunner { command, arguments, timeout ->
                                    ApiClient(targetEndpoint, targetToken).request(
                                        "/api/v1/execute", command, arguments, timeout
                                    )
                                }
                                val selected = benchmarkMode
                                val modes = benchmarkInput.copy(mode = selected).commands()
                                val results = CompanionBenchmarkExecution.run(
                                    config, modes, { benchmarkStop.get() },
                                    { command, progress ->
                                        runner.run(config, command, { benchmarkStop.get() }) { completed, _ ->
                                            progress(completed)
                                        }
                                    },
                                    { benchmarkLifecycle = benchmarkLifecycle.progressed(it) }
                                )
                                benchmarkLifecycle = benchmarkLifecycle.succeeded(BenchmarkReport.create(
                                    benchmarkLabel, java.net.URL(targetEndpoint).host, config, selected,
                                    results, context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: "unknown"
                                ))
                            } catch (e: Exception) {
                                benchmarkLifecycle = benchmarkLifecycle.failed(e.message ?: "Benchmark failed")
                            } finally { benchmarkLifecycle = benchmarkLifecycle.finished() }
                        }
                    } catch (e: Exception) {
                        benchmarkLifecycle = benchmarkLifecycle.failed("Invalid parameters: samples 1–1000, warmup 0–100, timeout 1–30s, payload 0–4096 bytes")
                    }
                }) { Text("Run benchmark") }
                OutlinedButton(enabled = benchmarkRunning, onClick = { benchmarkStop.set(true) }) {
                    Text("Cancel")
                }
            }
            ModuleNotice(benchmarkError, isError = true)
            benchmarkReport?.let { report ->
                Text("Run: ${report.runId}")
                for (item in report.results) {
                    Text("${item.command}: ${item.rttNs.size}/${item.attempted} successful · ${item.failures} failures")
                    Text("Phone RTT: ${item.summary(item.rttNs)}")
                    if (item.processingNs.isNotEmpty()) Text("Pi echo: ${item.summary(item.processingNs)}")
                    if (item.executionNs.isNotEmpty()) Text("Pi execution: ${item.summary(item.executionNs)}")
                }
                ModuleActions {
                    OutlinedButton(onClick = {
                        val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                        clipboard.setPrimaryClip(ClipData.newPlainText("GWAY benchmark JSON", report.json().toString(2)))
                    }) { Text("Copy JSON") }
                    OutlinedButton(onClick = {
                        val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                        clipboard.setPrimaryClip(ClipData.newPlainText("GWAY benchmark issue report", report.markdown()))
                        val intent = android.content.Intent(android.content.Intent.ACTION_VIEW,
                            android.net.Uri.parse("https://github.com/arthexis/gway-remote/issues/32"))
                        context.startActivity(intent)
                    }) { Text("Copy report + open issue #32") }
                    OutlinedButton(onClick = {
                        val intent = android.content.Intent(android.content.Intent.ACTION_SEND).apply {
                            type = "text/plain"
                            putExtra(android.content.Intent.EXTRA_TEXT, report.markdown())
                        }
                        context.startActivity(android.content.Intent.createChooser(intent, "Share benchmark"))
                    }) { Text("Share") }
                }
            }
        }
}
