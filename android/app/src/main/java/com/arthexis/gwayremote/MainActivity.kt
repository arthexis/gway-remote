package com.arthexis.gwayremote

import android.os.Bundle
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.ui.platform.LocalContext
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.compose.setContent
import androidx.lifecycle.viewmodel.compose.viewModel
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
import androidx.compose.ui.graphics.toArgb
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
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
        WindowCompat.setDecorFitsSystemWindows(window, false)
        window.setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE)
        UpdateNotifications.createChannel(this)
        UpdateNotifications.schedule(this)
        val store = SecretStore(this)
        setContent {
            val appearancePrefs = remember { getSharedPreferences("appearance", Context.MODE_PRIVATE) }
            var appearance by remember { mutableStateOf(AppearanceMode.fromStored(appearancePrefs.getString("mode", null))) }
            val dark = appearance.isDark(isSystemInDarkTheme())
            GwayRemoteTheme(darkTheme = dark) {
                val surfaceColor = MaterialTheme.colorScheme.background.toArgb()
                SideEffect {
                    window.statusBarColor = surfaceColor
                    window.navigationBarColor = surfaceColor
                    WindowInsetsControllerCompat(window, window.decorView).apply {
                        isAppearanceLightStatusBars = !dark
                        isAppearanceLightNavigationBars = !dark
                    }
                }
                CompanionScreen(store, appearance) { next ->
                    appearance = next
                    appearancePrefs.edit().putString("mode", next.name).apply()
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class, ExperimentalMaterial3Api::class)
@Composable
fun CompanionScreen(store: SecretStore, appearance: AppearanceMode = AppearanceMode.SYSTEM,
    onAppearanceChange: (AppearanceMode) -> Unit = {}) {
    val agentUiContext = LocalContext.current
    val operationModel: OperationViewModel = viewModel()
    val panelState = operationModel.panels
    val agentModel: AgentOpsViewModel = viewModel()
    val agentSendLoading = agentModel.sendLoading
    val agentSendResult = agentModel.sendResult
    val agentSendError = agentModel.sendError
    val agentObserveLoading = agentModel.observeLoading
    val agentObserveResult = agentModel.observeResult
    val agentObserveError = agentModel.observeError
    var endpoint by remember { mutableStateOf(store.endpoint.ifBlank { "https://remote.arthexis.com" }) }
    var token by remember { mutableStateOf(store.token) }
    var result by remember { mutableStateOf("Configure HTTPS endpoint and token") }
    var commands by remember { mutableStateOf(listOf<String>()) }
    var busy by remember { mutableStateOf(false) }
    var refreshing by remember { mutableStateOf(false) }
    var agentAssignmentsExpanded by remember { mutableStateOf(false) }
    val agentIssues = agentModel.issues
    val agentIssuesError = agentModel.issuesError
    val agentIssuesLoading = agentModel.issuesLoading
    var refreshStatus by remember { mutableStateOf("") }
    val simulatorStatus = operationModel.simulatorStatus
    var expandedWriteOperation by remember { mutableStateOf<String?>(null) }
    var lcdDuration by remember { mutableFloatStateOf(30f) }
    var lcdLine1 by remember { mutableStateOf("") }
    var lcdLine2 by remember { mutableStateOf("") }
    var availableMotifs by remember { mutableStateOf(listOf<String>()) }
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

    operationModel.bindCredentials { endpoint to token }
    agentModel.bindCredentials { endpoint to token }
    val scope = rememberCoroutineScope()
    LaunchedEffect(endpoint, token, panelState.panels.any { it.id == "sound" }) {
        if (endpoint.isNotBlank() && token.isNotBlank() &&
            panelState.panels.any { it.id == "sound" }) {
            try {
                val response = withContext(Dispatchers.IO) {
                    ApiClient(endpoint.trim(), token).request(
                        "/api/v1/execute", "sound-motifs", JSONObject())
                }
                val array = response.optJSONObject("result")?.optJSONArray("motifs")
                availableMotifs = if (array == null) emptyList()
                    else (0 until array.length()).map { array.getString(it) }
            } catch (_: Exception) {
                availableMotifs = emptyList()
            }
        }
    }

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
                if (command == "simulator-status" || command == "simulator-start" || command == "simulator-stop") {
                    val data = response.optJSONObject("result")
                    operationModel.updateSimulatorStatus(response)
                }
                result = response.toString(2)
            } catch (e: Exception) {
                result = e.message ?: "Connection failed"
                if (path.endsWith("/commands")) commands = emptyList()
            } finally { busy = false }
        }
    }

    fun refreshAll() {
        if (refreshing || busy || benchmarkRunning || updating) return
        refreshing = true
        refreshStatus = "Refreshing…"
        operationModel.refreshOpenPanels()
        if (agentAssignmentsExpanded && operationModel.panels.panels.any { it.id == "agent-ops" } && !agentModel.issuesLoading)
            agentModel.refreshAssignments()
        val targetEndpoint = endpoint.trim()
        val targetToken = token
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

    val benchmarkPanelContent: @Composable () -> Unit = {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
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
    }

    PullToRefreshBox(isRefreshing = refreshing, onRefresh = { refreshAll() },
        modifier = Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background).statusBarsPadding().navigationBarsPadding()) {
    Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background).imePadding().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text("GWay Remote", style = MaterialTheme.typography.headlineMedium)
            IconButton(onClick = { settingsOpen = !settingsOpen },
                modifier = Modifier.semantics { contentDescription = "API settings" }) {
                Text("⚙", style = MaterialTheme.typography.headlineMedium)
            }
        }
        if (settingsOpen) {
            HorizontalDivider()
            Text("Appearance", style = MaterialTheme.typography.titleMedium)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                AppearanceMode.entries.forEach { mode ->
                    FilterChip(selected = appearance == mode, onClick = { onAppearanceChange(mode) }, label = { Text(mode.label) })
                }
            }
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
        var githubHealthOpen by remember { mutableStateOf(false) }
        if (update != null) {
            Text("Update available: ${update!!.version}", style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.primary)
        }
        val unmatchedCommands = emptyList<String>() // Discovered commands are not palette actions
        OperationPalette(
            state = panelState,
            onOpen = operationModel::open,
            onClose = operationModel::close,
            onMove = operationModel::move,
            onRefresh = operationModel::refresh,
            onCsmsInspect = operationModel::inspectCsms,
            csmsView = operationModel.csmsView,
            onSelectCsmsView = operationModel::selectCsmsView,
            apiHealth = operationModel.apiHealth,
            systemStatus = operationModel.systemStatus,
            onRefreshSystem = operationModel::refreshSystem,
            agentAssignments = agentIssues,
            agentAssignmentsLoading = agentIssuesLoading,
            agentAssignmentsError = agentIssuesError,
            onRefreshAgentAssignments = agentModel::refreshAssignments,
            onAgentAssignmentsError = agentModel::reportAssignmentsError,
            agentAssignmentsExpanded = agentAssignmentsExpanded,
            onAgentAssignmentsExpanded = { agentAssignmentsExpanded = it },
            agentSendLoading = agentSendLoading,
            agentSendResult = agentSendResult,
            agentSendError = agentSendError,
            agentObserveLoading = agentObserveLoading,
            agentObserveResult = agentObserveResult,
            agentObserveError = agentObserveError,
            onAgentObserve = agentModel::observe,
            onAgentCopyPrompt = { ref ->
                agentModel.preview(ref) { prompt ->
                    val clipboard = agentUiContext.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                    clipboard.setPrimaryClip(ClipData.newPlainText("Agent issue prompt", prompt))
                }
            },
            onAgentSend = agentModel::send,
            onInspectTask = operationModel::inspectTask,
            taskDetail = operationModel.taskDetail,
            taskDetailLoading = operationModel.taskDetailLoading,
            taskDetailError = operationModel.taskDetailError,
            taskDetailSelection = operationModel.taskDetailSelection,
            onSelectSimulatorPeer = operationModel::selectSimulatorPeer,
            benchmarkContent = benchmarkPanelContent,
            simulatorStatus = simulatorStatus,
            onSimulatorCommand = operationModel::runConfirmedSimulator,
            onSimulatorRead = operationModel::simulatorRead,
            onSelectSimulatorRead = operationModel::selectSimulatorRead,
            motifs = availableMotifs,
            lcdNotification = operationModel.lcdNotification,
            soundNotification = operationModel.soundNotification,
            onNotificationInput = operationModel::notificationInput,
            onExecuteNotification = operationModel::executeNotification,
            onInput = operationModel::input,
            onExecute = operationModel::execute,
            extraActions = listOf(
                PaletteAction(
                    id = "github-health",
                    label = if (githubHealthOpen) "Hide GitHub Health" else "GitHub Health",
                    icon = "github",
                    onClick = { githubHealthOpen = !githubHealthOpen }
                ),
                PaletteAction(
                    id = "app-update",
                    label = if (updating) "Updating…" else "App update",
                    icon = "update",
                    onClick = { if (update == null) checkUpdates() else downloadUpdate() },
                    enabled = !updating,
                    attention = update != null
                )
            ) + unmatchedCommands.map { name ->
                PaletteAction("server-" + name, name, "list", { perform("/api/v1/execute", name) }, !busy)
            }
        )
        if (githubHealthOpen) {
            GitHubHealthPanel(endpoint = endpoint, token = token)
        }
        HorizontalDivider()
        if (refreshStatus.isNotBlank()) Text(refreshStatus, style = MaterialTheme.typography.bodySmall)
        if (updateStatus.isNotBlank() && !updateStatus.startsWith("App is up to date") &&
            !updateStatus.startsWith("Update available:")) {
            Text(updateStatus, style = MaterialTheme.typography.bodySmall)
        }

        if (busy) LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically) {
            Text("Response", style = MaterialTheme.typography.titleMedium)
            IconButton(enabled = result.isNotBlank(), onClick = {
                val clipboard = agentUiContext.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                clipboard.setPrimaryClip(ClipData.newPlainText("GWay Remote response", result))
            }, modifier = Modifier.semantics { contentDescription = "Copy response" }) {
                Text("⧉", style = MaterialTheme.typography.titleLarge)
            }
        }
        Text(result)
        Spacer(Modifier.height(LocalConfiguration.current.screenHeightDp.dp / 2))
    }
    }
}
