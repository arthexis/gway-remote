package com.arthexis.gwayremote

import android.os.Bundle
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.ui.platform.LocalContext
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.foundation.background
import androidx.compose.ui.graphics.Color
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.foundation.text.KeyboardOptions
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = android.graphics.Color.BLACK
        WindowCompat.setDecorFitsSystemWindows(window, false)
        WindowInsetsControllerCompat(window, window.decorView).isAppearanceLightStatusBars = false
        window.setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE)
        UpdateNotifications.createChannel(this)
        UpdateNotifications.schedule(this)
        val store = SecretStore(this)
        setContent { MaterialTheme { CompanionScreen(store) } }
    }
}

@OptIn(ExperimentalLayoutApi::class, ExperimentalMaterial3Api::class)
@Composable
fun CompanionScreen(store: SecretStore) {
    var endpoint by remember { mutableStateOf(store.endpoint) }
    var token by remember { mutableStateOf(store.token) }
    var result by remember { mutableStateOf("Configure HTTPS endpoint and token") }
    var commands by remember { mutableStateOf(listOf<String>()) }
    var busy by remember { mutableStateOf(false) }
    var refreshing by remember { mutableStateOf(false) }
    var agentIssues by remember { mutableStateOf(listOf<JSONObject>()) }
    var agentIssuesError by remember { mutableStateOf("") }
    var agentIssuesExpanded by remember { mutableStateOf(false) }
    var agentIssuesLoading by remember { mutableStateOf(false) }
    var refreshStatus by remember { mutableStateOf("") }
    var simulatorExpanded by remember { mutableStateOf(false) }
    var simulatorHost by remember { mutableStateOf("") }
    var simulatorPort by remember { mutableStateOf("9000") }
    var simulatorDiscovery by remember { mutableStateOf("Not checked") }
    var simulatorPeers by remember { mutableStateOf(listOf<String>()) }
    var simulatorPeerMenu by remember { mutableStateOf(false) }
    var simulatorStatus by remember { mutableStateOf("Not checked") }
    var simulatorOutput by remember { mutableStateOf("") }
    var simulatorTruncated by remember { mutableStateOf(false) }
    var simulatorResultsLoaded by remember { mutableStateOf(false) }
    var simulatorResultsError by remember { mutableStateOf("") }
    var simulatorOutcome by remember { mutableStateOf("unknown") }
    var simulatorExitCode by remember { mutableStateOf("") }
    var csmsExpanded by remember { mutableStateOf(false) }
    var csmsView by remember { mutableStateOf("status") }
    var csmsMenuOpen by remember { mutableStateOf(false) }
    var csmsOutput by remember { mutableStateOf("") }
    var csmsTruncated by remember { mutableStateOf(false) }
    var csmsHealthy by remember { mutableStateOf<Boolean?>(null) }
    var csmsReason by remember { mutableStateOf("") }
    var expandedWriteOperation by remember { mutableStateOf<String?>(null) }
    var lcdDuration by remember { mutableFloatStateOf(30f) }
    var lcdLine1 by remember { mutableStateOf("") }
    var lcdLine2 by remember { mutableStateOf("") }
    var selectedSound by remember { mutableStateOf("notice") }
    var soundMenuOpen by remember { mutableStateOf(false) }
    var settingsOpen by remember { mutableStateOf(endpoint.isBlank() || token.isBlank()) }
    var benchmarkExpanded by remember { mutableStateOf(false) }
    var benchmarkSamples by remember { mutableStateOf("100") }
    var benchmarkWarmup by remember { mutableStateOf("5") }
    var benchmarkTimeout by remember { mutableStateOf("5") }
    var benchmarkPayload by remember { mutableStateOf("0") }
    var benchmarkProgress by remember { mutableIntStateOf(0) }
    var benchmarkRunning by remember { mutableStateOf(false) }
    var benchmarkReport by remember { mutableStateOf<BenchmarkReport?>(null) }
    var benchmarkMode by remember { mutableStateOf(BenchmarkMode.BOTH) }
    var benchmarkLabel by remember { mutableStateOf("Unspecified") }
    var benchmarkError by remember { mutableStateOf("") }
    val benchmarkStop = remember { java.util.concurrent.atomic.AtomicBoolean(false) }

    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val notificationPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { /* Background checks continue; alerts require permission. */ }
    LaunchedEffect(Unit) {
        if (android.os.Build.VERSION.SDK_INT >= 33 &&
            androidx.core.content.ContextCompat.checkSelfPermission(
                context, android.Manifest.permission.POST_NOTIFICATIONS
            ) != android.content.pm.PackageManager.PERMISSION_GRANTED
        ) notificationPermissionLauncher.launch(android.Manifest.permission.POST_NOTIFICATIONS)
    }
    val installedCode = if (android.os.Build.VERSION.SDK_INT >= 33)
        context.packageManager.getPackageInfo(context.packageName, android.content.pm.PackageManager.PackageInfoFlags.of(0)).longVersionCode
    else @Suppress("DEPRECATION") context.packageManager.getPackageInfo(context.packageName, 0).longVersionCode
    var update by remember { mutableStateOf<AvailableUpdate?>(null) }
    var updateStatus by remember { mutableStateOf("") }
    var updating by remember { mutableStateOf(false) }
    var apk by remember {
        mutableStateOf(java.io.File(context.cacheDir, "gway-remote-update.apk").takeIf { it.isFile })
    }
    var awaitingInstallPermission by remember { mutableStateOf(false) }

    fun launchInstaller() {
        val candidate = update
        val file = apk
        if (candidate == null || file == null) {
            updateStatus = "No verified update available; download it again"
            return
        }
        if (updating) return
        updating = true
        updateStatus = "Checking downloaded APK…"
        scope.launch {
            try {
                withContext(Dispatchers.IO) { AppUpdater.verifyDownloadedApk(context, file, candidate) }
                AppUpdater.install(context, file)
                updateStatus = "Android installer requested. Confirm the update in the system dialog."
            } catch (e: Exception) {
                updateStatus = "Installation could not start: ${e.message ?: e.javaClass.simpleName}"
            } finally { updating = false }
        }
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) {
        if (awaitingInstallPermission) {
            awaitingInstallPermission = false
            if (AppUpdater.canInstall(context)) launchInstaller()
            else updateStatus = "Installation permission not granted; allow installs from GWay Remote"
        }
    }

    fun requestInstall() {
        if (updating) return
        if (!AppUpdater.canInstall(context)) {
            awaitingInstallPermission = true
            updateStatus = "Grant installation permission, then return to GWay Remote"
            try {
                permissionLauncher.launch(AppUpdater.installPermissionIntent(context))
            } catch (e: Exception) {
                awaitingInstallPermission = false
                updateStatus = "Unable to open installation settings: ${e.message}"
            }
        } else launchInstaller()
    }

    fun checkUpdates() {
        if (updating) return
        updating = true
        updateStatus = "Checking releases…"
        scope.launch {
            try {
                update = withContext(Dispatchers.IO) { AppUpdater.check(installedCode) }
                updateStatus = if (update == null) "App is up to date" else "Update available: ${update!!.version}"
            } catch (e: Exception) { updateStatus = e.message ?: "Update check failed" }
            finally { updating = false }
        }
    }

    fun downloadUpdate() {
        val candidate = update ?: return
        if (updating) return
        updating = true
        updateStatus = "Downloading and verifying…"
        scope.launch {
            var downloaded = false
            try {
                apk = withContext(Dispatchers.IO) { AppUpdater.download(context, candidate) }
                updateStatus = "Download verified; ready to install"
                downloaded = true
            } catch (e: Exception) { updateStatus = e.message ?: "Update failed" }
            finally { updating = false }
            if (downloaded) requestInstall()
        }
    }
    LaunchedEffect(Unit) { checkUpdates() }

    fun perform(path: String, command: String? = null, arguments: JSONObject = JSONObject()) {
        if (busy) return
        busy = true
        scope.launch {
            try {
                val response = withContext(Dispatchers.IO) {
                    ApiClient(endpoint.trim(), token).request(path, command, arguments)
                }
                if (path.endsWith("/commands")) {
                    val entries = response.getJSONArray("commands")
                    commands = (0 until entries.length()).mapNotNull { index ->
                        val item = entries.getJSONObject(index)
                        if (item.optBoolean("read_only") && (item.optJSONObject("arguments")?.length() ?: 0) == 0)
                            item.optString("name").takeIf { it.isNotBlank() } else null
                    }
                }
                if (command == "probe-csms") {
                    val data = response.optJSONObject("result")
                    csmsHealthy = data?.optBoolean("healthy")
                    csmsReason = data?.optString("reason") ?: "No diagnostic details"
                }
                if (command == "csms-view") {
                    val data = response.optJSONObject("result")
                    csmsOutput = data?.optString("output") ?: response.toString(2)
                    csmsTruncated = data?.optBoolean("truncated") ?: false
                }
                if (command == "simulator-results") {
                    val data = response.optJSONObject("result")
                    if (data == null) {
                        simulatorResultsError = "Invalid results response"
                    } else {
                        simulatorOutput = data.optString("output", "")
                        simulatorTruncated = data.optBoolean("truncated", false)
                        simulatorResultsLoaded = true
                        simulatorOutcome = data.optString("outcome", "unknown")
                        simulatorExitCode = if (data.has("exit_code")) data.optInt("exit_code").toString() else ""
                        simulatorResultsError = ""
                        simulatorStatus = "${data.optString("state", "unknown")} — " +
                            data.optString("target", "")
                    }
                }
                if (command == "simulator-discover") {
                    val data = response.optJSONObject("result")
                    val peers = data?.optJSONArray("peers")
                    simulatorPeers = if (peers == null) emptyList() else
                        (0 until peers.length()).mapNotNull { index ->
                            peers.optJSONObject(index)?.optString("host")?.takeIf { it.isNotBlank() }
                        }
                    simulatorDiscovery = "Discovered Ethernet peers: ${simulatorPeers.size}"
                }
                if (command == "simulator-status" || command == "simulator-start" || command == "simulator-stop") {
                    val data = response.optJSONObject("result")
                    simulatorStatus = "${data?.optString("state") ?: "unknown"} — " +
                        (data?.optString("target") ?: "")
                }
                result = response.toString(2)
            } catch (e: Exception) {
                result = e.message ?: "Connection failed"
                if (path.endsWith("/commands")) commands = emptyList()
                if (command == "simulator-results") simulatorResultsError = e.message ?: "Results unavailable"
            } finally { busy = false }
        }
    }

    fun refreshAgentIssues() {
        if (agentIssuesLoading) return
        agentIssuesLoading = true
        scope.launch {
            try {
                val response = withContext(Dispatchers.IO) {
                    ApiClient(endpoint.trim(), token).request(
                        "/api/v1/execute", "codex-issues", JSONObject())
                }
                val entries = response.getJSONObject("result").getJSONArray("issues")
                agentIssues = (0 until entries.length()).map { entries.getJSONObject(it) }
                agentIssuesError = ""
            } catch (e: Exception) {
                agentIssuesError = e.message ?: "Assignments unavailable"
            } finally {
                agentIssuesLoading = false
            }
        }
    }

    fun refreshAll() {
        if (refreshing || busy || benchmarkRunning || updating) return
        refreshing = true
        refreshStatus = "Refreshing…"
        val targetEndpoint = endpoint.trim()
        val targetToken = token
        val selectedView = csmsView
        val refreshCsms = csmsExpanded
        val refreshSimulator = simulatorExpanded
        val refreshResults = simulatorResultsLoaded
        scope.launch {
            val failures = mutableListOf<String>()
            try {
                val client = try { ApiClient(targetEndpoint, targetToken) }
                    catch (e: Exception) {
                        failures.add("API settings: ${e.message}")
                        null
                    }
                if (client != null) {
                    suspend fun fetch(label: String, path: String, command: String? = null,
                                      args: JSONObject = JSONObject()): JSONObject? =
                        try { withContext(Dispatchers.IO) { client.request(path, command, args) } }
                        catch (e: Exception) { failures.add("${label}: ${e.message}"); null }
                    fetch("Health", "/api/v1/health")?.let { result = it.toString(2) }
                    fetch("Quick status", "/api/v1/execute", "status-quick")?.let { result = it.toString(2) }
                    fetch("Commands", "/api/v1/commands")?.let { response ->
                        val entries = response.getJSONArray("commands")
                        commands = (0 until entries.length()).mapNotNull { index ->
                            val item = entries.getJSONObject(index)
                            if (item.optBoolean("read_only") &&
                                (item.optJSONObject("arguments")?.length() ?: 0) == 0)
                                item.optString("name").takeIf { it.isNotBlank() } else null
                        }
                    }
                    if (refreshCsms) {
                        fetch("CSMS health", "/api/v1/execute", "probe-csms")?.optJSONObject("result")?.let {
                            csmsHealthy = it.optBoolean("healthy")
                            csmsReason = it.optString("reason", "")
                        }
                        if (csmsOutput.isNotBlank()) {
                            fetch("CSMS view", "/api/v1/execute", "csms-view",
                                JSONObject().put("view", selectedView))?.optJSONObject("result")?.let {
                                csmsOutput = it.optString("output", "")
                                csmsTruncated = it.optBoolean("truncated")
                            }
                        }
                    }
                    if (refreshSimulator) {
                        fetch("Simulator", "/api/v1/execute", "simulator-status")?.optJSONObject("result")?.let {
                            simulatorStatus = "${it.optString("state", "unknown")} — ${it.optString("target", "")}"
                        }
                        if (refreshResults) {
                            fetch("Simulator results", "/api/v1/execute", "simulator-results")?.optJSONObject("result")?.let {
                                simulatorOutput = it.optString("output", "")
                                simulatorTruncated = it.optBoolean("truncated")
                                simulatorOutcome = it.optString("outcome", "unknown")
                                simulatorExitCode = if (it.has("exit_code")) it.optInt("exit_code").toString() else ""
                                simulatorResultsError = ""
                            }
                        }
                    }
                }
                try {
                    updateStatus = "Checking releases…"
                    update = withContext(Dispatchers.IO) { AppUpdater.check(installedCode) }
                    updateStatus = if (update == null) "App is up to date" else "Update available: ${update!!.version}"
                } catch (e: Exception) {
                    failures.add("App update: ${e.message}")
                    updateStatus = "Update check failed: ${e.message}"
                }
                refreshStatus = if (failures.isEmpty()) "Refresh completed" else
                    "Refresh partially failed: ${failures.joinToString("; ")}"
            } finally { refreshing = false }
        }
    }

    PullToRefreshBox(isRefreshing = refreshing, onRefresh = { refreshAll() },
        modifier = Modifier.fillMaxSize().background(Color.Black).statusBarsPadding().navigationBarsPadding()) {
    Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background).imePadding().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text("GWay Remote", style = MaterialTheme.typography.headlineMedium)
            IconButton(onClick = { settingsOpen = !settingsOpen },
                modifier = Modifier.semantics { contentDescription = "API settings" }) {
                Text("⚙", style = MaterialTheme.typography.headlineMedium)
            }
        }
        if (refreshStatus.isNotBlank()) Text(refreshStatus, style = MaterialTheme.typography.bodySmall)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            TextButton(onClick = {
                agentIssuesExpanded = !agentIssuesExpanded
                if (agentIssuesExpanded) refreshAgentIssues()
            }) { Text(if (agentIssuesExpanded) "Agent assignments ▾" else "Agent assignments ▸") }
            if (agentIssuesExpanded) TextButton(
                onClick = { refreshAgentIssues() }, enabled = !agentIssuesLoading
            ) { Text("Refresh") }
        }
        if (agentIssuesExpanded) {
            if (agentIssuesLoading) LinearProgressIndicator(Modifier.fillMaxWidth())
            if (agentIssuesError.isNotBlank()) Text(agentIssuesError, color = MaterialTheme.colorScheme.error)
            agentIssues.forEach { issue ->
                val url = issue.optString("url")
                val state = issue.optString("state", "queued")
                val sent = issue.optString("sent_at")
                val status = when (state) {
                    "sent" -> {
                        val elapsed = try {
                            val start = java.time.OffsetDateTime.parse(sent).toInstant()
                            java.time.Duration.between(start, java.time.Instant.now()).seconds.coerceAtLeast(0)
                        } catch (_: Exception) { 0L }
                        "Sent " + when {
                            elapsed < 60 -> "${elapsed}s"
                            elapsed < 3600 -> "${elapsed / 60}m"
                            elapsed < 86400 -> "${elapsed / 3600}h"
                            else -> "${elapsed / 86400}d"
                        }
                    }
                    "attended" -> "Attended"
                    else -> "Queued"
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Column(Modifier.weight(1f)) {
                        TextButton(onClick = {
                            try { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }
                            catch (_: Exception) { agentIssuesError = "Unable to open GitHub" }
                        }) { Text("#${issue.optInt("number")} ${issue.optString("title")}") }
                        Text("${issue.optString("repository")} · $status",
                            style = MaterialTheme.typography.bodySmall)
                    }
                    Text("☏ ${issue.optInt("comments")}",
                        modifier = Modifier.padding(top = 12.dp))
                    IconButton(onClick = {
                        val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                        clipboard.setPrimaryClip(ClipData.newPlainText("GitHub issue", url))
                    }, modifier = Modifier.semantics { contentDescription = "Copy issue URL" }) {
                        Text("↗")
                    }
                }
                HorizontalDivider()
            }
        }

        if (update != null) {
            Text("Update available: ${update!!.version} (code ${update!!.versionCode}); installed code $installedCode")
            Button(enabled = !updating, onClick = { downloadUpdate() }) { Text("Update app") }
        }
        if (updateStatus.isNotBlank() && (update != null || !updateStatus.startsWith("App is up to date"))) {
            Text(updateStatus)
        }
        if (settingsOpen) {
            HorizontalDivider()
            Text("API settings", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(endpoint, { endpoint = it }, label = { Text("HTTPS endpoint") },
                modifier = Modifier.fillMaxWidth(), singleLine = true)
            OutlinedTextField(token, { token = it }, label = { Text("Bearer token") },
                visualTransformation = androidx.compose.ui.text.input.PasswordVisualTransformation(),
                modifier = Modifier.fillMaxWidth(), singleLine = true)
            Button(onClick = {
                try {
                    ApiClient(endpoint.trim(), token)
                    store.endpoint = endpoint.trim()
                    store.token = token
                    settingsOpen = false
                    result = "Connection settings saved"
                } catch (e: Exception) { result = e.message ?: "Invalid settings" }
            }) { Text("Save settings") }
        }
        HorizontalDivider()
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text("Benchmark", style = MaterialTheme.typography.titleMedium)
            TextButton(onClick = { benchmarkExpanded = !benchmarkExpanded }) {
                Text(if (benchmarkExpanded) "Hide" else "Expand")
            }
        }
        if (benchmarkExpanded) {
            Text("Authenticated echo and read-only status · connected node", style = MaterialTheme.typography.bodySmall)
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                for (mode in BenchmarkMode.entries) {
                    FilterChip(selected = benchmarkMode == mode, onClick = { benchmarkMode = mode },
                        label = { Text(mode.name.lowercase().replaceFirstChar { it.uppercase() }) })
                }
            }
            OutlinedTextField(benchmarkLabel, { benchmarkLabel = it }, label = { Text("Connection label (AP / LAN / remote)") },
                modifier = Modifier.fillMaxWidth(), singleLine = true)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(benchmarkSamples, { benchmarkSamples = it }, label = { Text("Samples") },
                    modifier = Modifier.weight(1f), singleLine = true)
                OutlinedTextField(benchmarkWarmup, { benchmarkWarmup = it }, label = { Text("Warmup") },
                    modifier = Modifier.weight(1f), singleLine = true)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(benchmarkTimeout, { benchmarkTimeout = it }, label = { Text("Timeout (s)") },
                    modifier = Modifier.weight(1f), singleLine = true)
                OutlinedTextField(benchmarkPayload, { benchmarkPayload = it }, label = { Text("Payload (bytes)") },
                    modifier = Modifier.weight(1f), singleLine = true)
            }
            if (benchmarkRunning) {
                Text("Progress: $benchmarkProgress / ${(benchmarkSamples.toIntOrNull() ?: 0) * (if (benchmarkMode == BenchmarkMode.BOTH) 2 else 1)}")
                LinearProgressIndicator(
                    progress = { benchmarkProgress.toFloat() / ((benchmarkSamples.toIntOrNull()?.coerceAtLeast(1) ?: 1) * (if (benchmarkMode == BenchmarkMode.BOTH) 2 else 1)) },
                    modifier = Modifier.fillMaxWidth()
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(enabled = !benchmarkRunning, onClick = {
                    try {
                        val config = BenchmarkConfig(
                            samples = benchmarkSamples.toInt(),
                            warmup = benchmarkWarmup.toInt(),
                            timeoutMs = benchmarkTimeout.toInt() * 1000,
                            payloadBytes = benchmarkPayload.toInt()
                        )
                        benchmarkError = ""
                        benchmarkReport = null
                        benchmarkProgress = 0
                        benchmarkRunning = true
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
                                val modes = if (selected == BenchmarkMode.BOTH)
                                    listOf("benchmark-echo", "status") else
                                    listOf(if (selected == BenchmarkMode.ECHO) "benchmark-echo" else "status")
                                val results = mutableListOf<BenchmarkResult>()
                                for ((index, command) in modes.withIndex()) {
                                    if (benchmarkStop.get()) break
                                    results.add(runner.run(config, command, { benchmarkStop.get() }) { completed, _ ->
                                        benchmarkProgress = index * config.samples + completed
                                    })
                                }
                                benchmarkReport = BenchmarkReport.create(
                                    benchmarkLabel, java.net.URL(targetEndpoint).host, config, selected,
                                    results, context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: "unknown"
                                )
                            } catch (e: Exception) {
                                benchmarkError = e.message ?: "Benchmark failed"
                            } finally { benchmarkRunning = false }
                        }
                    } catch (e: Exception) {
                        benchmarkError = "Invalid parameters: samples 1–1000, warmup 0–100, timeout 1–30s, payload 0–4096 bytes"
                    }
                }) { Text("Run benchmark") }
                OutlinedButton(enabled = benchmarkRunning, onClick = { benchmarkStop.set(true) }) {
                    Text("Cancel")
                }
            }
            if (benchmarkError.isNotBlank()) Text(benchmarkError)
            benchmarkReport?.let { report ->
                Text("Run: ${report.runId}")
                for (item in report.results) {
                    Text("${item.command}: ${item.rttNs.size}/${item.attempted} successful · ${item.failures} failures")
                    Text("Phone RTT: ${item.summary(item.rttNs)}")
                    if (item.processingNs.isNotEmpty()) Text("Pi echo: ${item.summary(item.processingNs)}")
                    if (item.executionNs.isNotEmpty()) Text("Pi execution: ${item.summary(item.executionNs)}")
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
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
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(enabled = !busy, onClick = { perform("/api/v1/health") }) { Text("Test") }
            Button(enabled = !busy, onClick = { perform("/api/v1/commands") }) { Text("Commands") }
        }
        Text("Write operations", style = MaterialTheme.typography.titleMedium)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp)) {
            OutlinedButton(onClick = {
                expandedWriteOperation = if (expandedWriteOperation == "lcd-message") null else "lcd-message"
            }) { Text(if (expandedWriteOperation == "lcd-message") "LCD message ▴" else "LCD message ▾") }
            OutlinedButton(onClick = {
                expandedWriteOperation = if (expandedWriteOperation == "sound-play") null else "sound-play"
            }) { Text(if (expandedWriteOperation == "sound-play") "Play sound ▴" else "Play sound ▾") }
        }
        if (expandedWriteOperation == "lcd-message") {
            Text("LCD (16 × 2)", style = MaterialTheme.typography.titleSmall)
        OutlinedTextField(lcdLine1, { next ->
            if (next.length <= 16 && next.all { it.code in 32..126 }) lcdLine1 = next
        }, label = { Text("Line 1 (${lcdLine1.length}/16)") },
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Characters),
            modifier = Modifier.fillMaxWidth(), singleLine = true)
        OutlinedTextField(lcdLine2, { next ->
            if (next.length <= 16 && next.all { it.code in 32..126 }) lcdLine2 = next
        }, label = { Text("Line 2 (${lcdLine2.length}/16)") },
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Characters),
            modifier = Modifier.fillMaxWidth(), singleLine = true)
        Row(Modifier.fillMaxWidth(), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(enabled = !busy && (lcdLine1.isNotEmpty() || lcdLine2.isNotEmpty()), onClick = {
                perform("/api/v1/execute", "lcd-message",
                    JSONObject().put("line1", lcdLine1).put("line2", lcdLine2)
                        .put("duration_seconds", lcdDuration.toInt()))
            }) { Text("Show on LCD") }
            Column(Modifier.weight(1f)) {
                Text("Duration: ${lcdDuration.toInt() / 60}:${(lcdDuration.toInt() % 60).toString().padStart(2, '0')}")
                Slider(value = lcdDuration, onValueChange = { lcdDuration = it },
                    valueRange = 30f..300f, steps = 8)
            }
        }
        }
        if (expandedWriteOperation == "sound-play") {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
        Box {
            OutlinedButton(onClick = { soundMenuOpen = true }) { Text("Sound: $selectedSound ▾") }
            DropdownMenu(expanded = soundMenuOpen, onDismissRequest = { soundMenuOpen = false }) {
                listOf("ok", "notice", "attention", "warning", "error", "busy", "critical").forEach { name ->
                    DropdownMenuItem(text = { Text(name) }, onClick = {
                        selectedSound = name
                        soundMenuOpen = false
                    })
                }
            }
        }
        Button(enabled = !busy, onClick = {
            perform("/api/v1/execute", "sound-play", JSONObject().put("sound", selectedSound))
        }) { Text("Play sound") }
        }
        }
        Text("Read operations", style = MaterialTheme.typography.titleMedium)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp)) {
        commands.filter { it != "probe-csms" && it != "simulator-status" && it != "simulator-results" }.forEach { name ->
            OutlinedButton(enabled = !busy, onClick = { perform("/api/v1/execute", name) }) {
                Text(name)
            }
        }
        }
        Text("CSMS", style = MaterialTheme.typography.titleMedium)
        OutlinedButton(onClick = { csmsExpanded = !csmsExpanded }) {
            Text(if (csmsExpanded) "CSMS inspection ▴" else "CSMS inspection ▾")
        }
        if (csmsExpanded) {
            Button(enabled = !busy, onClick = { perform("/api/v1/execute", "probe-csms") }) {
                Text("Refresh CSMS health")
            }
            if (csmsHealthy != null) {
                Text(if (csmsHealthy == true) "● Healthy" else "● Needs attention",
                    color = if (csmsHealthy == true) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error)
                Text(csmsReason)
            }
            Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Box(Modifier.weight(1f)) {
                    OutlinedButton(onClick = { csmsMenuOpen = true }) { Text("View: $csmsView ▾") }
                    DropdownMenu(expanded = csmsMenuOpen, onDismissRequest = { csmsMenuOpen = false }) {
                        listOf("status", "chargers", "charge-points", "transactions", "events",
                            "alerts", "rfid-report", "report").forEach { view ->
                            DropdownMenuItem(text = { Text(view) }, onClick = {
                                csmsView = view
                                csmsMenuOpen = false
                            })
                        }
                    }
                }
                Button(enabled = !busy, onClick = {
                    perform("/api/v1/execute", "csms-view", JSONObject().put("view", csmsView))
                }) { Text("Inspect") }
            }
            if (csmsOutput.isNotBlank()) {
                if (csmsTruncated) Text("Output truncated to 64 KB", color = MaterialTheme.colorScheme.error)
                Text(csmsOutput, style = MaterialTheme.typography.bodySmall)
            }
        }
        Text("OCPP Simulator", style = MaterialTheme.typography.titleMedium)
        OutlinedButton(onClick = { simulatorExpanded = !simulatorExpanded }) {
            Text(if (simulatorExpanded) "Ethernet target ▴" else "Ethernet target ▾")
        }
        LaunchedEffect(simulatorExpanded, endpoint, token) {
            if (simulatorExpanded && endpoint.isNotBlank() && token.isNotBlank()) {
                try {
                    val response = withContext(Dispatchers.IO) {
                        ApiClient(endpoint.trim(), token).request(
                            "/api/v1/execute", "simulator-status")
                    }
                    val data = response.optJSONObject("result")
                    simulatorStatus = "${data?.optString("state") ?: "unknown"} — " +
                        (data?.optString("target") ?: "")
                } catch (e: Exception) {
                    simulatorStatus = e.message ?: "Status unavailable"
                }
            }
        }
        if (simulatorExpanded) {
            Text("Simulation: $simulatorStatus")
            OutlinedButton(enabled = !busy, onClick = {
                perform("/api/v1/execute", "simulator-status")
            }) { Text("Refresh status") }
            OutlinedTextField(simulatorHost, { simulatorHost = it },
                label = { Text("CSMS IPv4 (blank = discover)") },
                modifier = Modifier.fillMaxWidth(), singleLine = true)
            OutlinedTextField(simulatorPort, { simulatorPort = it },
                label = { Text("CSMS port") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
            Button(enabled = !busy && (simulatorPort.toIntOrNull()?.let { it in 1..65535 } == true),
                onClick = {
                    val args = JSONObject().put("port", simulatorPort.toInt())
                    if (simulatorHost.isNotBlank()) args.put("host", simulatorHost.trim())
                    perform("/api/v1/execute", "simulator-discover", args)
                }) { Text("Discover / check target") }
            Text(simulatorDiscovery, style = MaterialTheme.typography.bodySmall)
            if (simulatorPeers.isNotEmpty()) {
                Box {
                    OutlinedButton(onClick = { simulatorPeerMenu = true }) {
                        Text("Select discovered target ▾")
                    }
                    DropdownMenu(expanded = simulatorPeerMenu,
                        onDismissRequest = { simulatorPeerMenu = false }) {
                        simulatorPeers.forEach { peer ->
                            DropdownMenuItem(text = { Text(peer) }, onClick = {
                                simulatorHost = peer
                                simulatorPeerMenu = false
                            })
                        }
                    }
                }
            }
            SimulatorControls(simulatorHost, simulatorPort, simulatorStatus, busy) { command, args ->
                perform("/api/v1/execute", command, args)
            }
            HorizontalDivider()
            Text("Simulation results", style = MaterialTheme.typography.titleMedium)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(enabled = !busy, onClick = {
                    perform("/api/v1/execute", "simulator-results")
                }) { Text("Refresh results") }
                OutlinedButton(enabled = simulatorResultsLoaded && simulatorOutput.isNotEmpty(),
                    onClick = {
                        val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                        clipboard.setPrimaryClip(ClipData.newPlainText("Simulator output", simulatorOutput))
                    }) { Text("Copy output") }
            }
            if (simulatorResultsError.isNotBlank()) {
                Text(simulatorResultsError, color = MaterialTheme.colorScheme.error)
            }
            if (simulatorResultsLoaded) {
                Text("Process: $simulatorStatus")
                if (simulatorStatus.startsWith("stopped")) {
                    Text(when (simulatorOutcome) {
                        "completed" -> "Completed successfully (exit 0)"
                        "failed" -> "Failed (exit $simulatorExitCode)"
                        else -> "Stopped — completion outcome unavailable"
                    })
                }
                if (simulatorTruncated) {
                    Text("Output truncated to last 32 KB", color = MaterialTheme.colorScheme.error)
                }
                Text("OCPP activity (best-effort from log)",
                    style = MaterialTheme.typography.titleSmall)
                val milestones = remember(simulatorOutput, simulatorTruncated) {
                    SimulatorActivitySummary.parse(simulatorOutput, simulatorTruncated)
                }
                if (milestones.isEmpty()) {
                    Text("No recognizable OCPP milestones in captured output.")
                } else {
                    milestones.forEach { milestone ->
                        Text("${milestone.label}: ${milestone.evidence}",
                            style = MaterialTheme.typography.bodySmall)
                    }
                }
                Text("Raw output", style = MaterialTheme.typography.titleSmall)
                Text(if (simulatorOutput.isEmpty()) "No output captured" else simulatorOutput,
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.fillMaxWidth().heightIn(max = 320.dp)
                        .verticalScroll(rememberScrollState()))
            } else {
                Text("Refresh to load captured simulator output.")
            }
        }
        if (busy) LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        Text("Response", style = MaterialTheme.typography.titleMedium)
        Text(result)
        Spacer(Modifier.height(LocalConfiguration.current.screenHeightDp.dp / 2))
    }
    }
}
