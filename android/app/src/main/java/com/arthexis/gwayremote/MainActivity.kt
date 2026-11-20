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
import androidx.activity.compose.BackHandler
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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Refresh
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
    var quotationsOpen by remember { mutableStateOf(false) }
    var localPanels by remember { mutableStateOf(LocalPanelState()) }
    var settings by remember {
        mutableStateOf(CompanionSettingsState.initial(
            store.endpoint.ifBlank { "https://remote.arthexis.com" }, store.token
        ))
    }
    val endpoint = settings.endpoint
    val token = settings.token
    var commandState by remember { mutableStateOf(CompanionCommandState()) }
    val result = commandState.result
    val commands = commandState.commands
    val busy = commandState.busy
    var refreshState by remember { mutableStateOf(CompanionRefreshState()) }
    val refreshing = refreshState.running
    var agentAssignmentsExpanded by remember { mutableStateOf(false) }
    val agentIssues = agentModel.issues
    val agentIssuesError = agentModel.issuesError
    val agentIssuesLoading = agentModel.issuesLoading
    val refreshStatus = refreshState.status
    var expandedWriteOperation by remember { mutableStateOf<String?>(null) }
    var lcdDuration by remember { mutableFloatStateOf(30f) }
    var lcdLine1 by remember { mutableStateOf("") }
    var lcdLine2 by remember { mutableStateOf("") }
    var soundMotifs by remember { mutableStateOf(CompanionSoundMotifsState()) }
    var selectedSound by remember { mutableStateOf("notice") }
    var soundMenuOpen by remember { mutableStateOf(false) }
    val settingsOpen = settings.open
    var benchmarkExpanded by remember { mutableStateOf(false) }
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

    operationModel.bindCredentials { endpoint to token }
    agentModel.bindCredentials { endpoint to token }
    val scope = rememberCoroutineScope()
    LaunchedEffect(endpoint, token, panelState.panels.any { it.id == "sound" || it.id == "notifications" }) {
        if (endpoint.isNotBlank() && token.isNotBlank() &&
            panelState.panels.any { it.id == "sound" || it.id == "notifications" }) {
            try {
                val response = withContext(Dispatchers.IO) {
                    ApiClient(endpoint.trim(), token).request(
                        "/api/v1/execute", "sound-motifs", JSONObject())
                }
                soundMotifs = soundMotifs.loaded(response)
            } catch (_: Exception) {
                soundMotifs = soundMotifs.failed()
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
    var updateState by remember { mutableStateOf(CompanionUpdateState()) }
    val updateStatus = updateState.status
    val updating = updateState.running
    var apk by remember {
        mutableStateOf(java.io.File(context.cacheDir, "gway-remote-update.apk").takeIf { it.isFile })
    }
    var installPermissionState by remember { mutableStateOf(CompanionInstallPermissionState()) }

    fun launchInstaller() {
        val candidate = update
        val file = apk
        if (candidate == null || file == null) {
            updateState = updateState.status("No verified update available; download it again")
            return
        }
        if (updating) return
        updateState = updateState.started("Checking downloaded APK…")
        scope.launch {
            CompanionUpdateTransfer.install(
                verify = { withContext(Dispatchers.IO) { AppUpdater.verifyDownloadedApk(context, file, candidate) } },
                launch = { AppUpdater.install(context, file) },
                onStatus = { updateState = updateState.status(it) },
                onFinished = { updateState = updateState.finished() }
            )
        }
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) {
        if (installPermissionState.awaitingResult) {
            val outcome = installPermissionState.result(AppUpdater.canInstall(context))
            installPermissionState = outcome.state
            if (outcome.launchInstaller) launchInstaller()
            else outcome.status?.let { updateState = updateState.status(it) }
        }
    }

    fun requestInstall() {
        if (updating) return
        if (!AppUpdater.canInstall(context)) {
            installPermissionState = installPermissionState.requested()
            updateState = updateState.status("Grant installation permission, then return to GWay Remote")
            try {
                permissionLauncher.launch(AppUpdater.installPermissionIntent(context))
            } catch (e: Exception) {
                val outcome = installPermissionState.launchFailed(e.message)
                installPermissionState = outcome.state
                outcome.status?.let { updateState = updateState.status(it) }
            }
        } else launchInstaller()
    }

    fun checkUpdates() {
        if (updating) return
        updateState = updateState.started("Checking releases…")
        scope.launch {
            CompanionUpdateCheck.run(
                check = { withContext(Dispatchers.IO) { AppUpdater.check(installedCode) } },
                onUpdate = { update = it },
                onStatus = { updateState = updateState.status(it) },
                onFinished = { updateState = updateState.finished() }
            )
        }
    }

    fun downloadUpdate() {
        val candidate = update ?: return
        if (updating) return
        updateState = updateState.started("Downloading and verifying…")
        scope.launch {
            CompanionUpdateTransfer.download(
                transfer = { withContext(Dispatchers.IO) { AppUpdater.download(context, candidate) } },
                onDownloaded = { apk = it },
                onStatus = { updateState = updateState.status(it) },
                onFinished = { updateState = updateState.finished() },
                requestInstall = { requestInstall() }
            )
        }
    }
    LaunchedEffect(Unit) { checkUpdates() }

    fun perform(path: String, command: String? = null, arguments: JSONObject = JSONObject()) {
        if (busy) return
        commandState = commandState.started()
        scope.launch {
            try {
                CompanionCommandActions.perform(
                    path,
                    { withContext(Dispatchers.IO) { ApiClient(endpoint.trim(), token).request(path, command, arguments) } },
                    { commandState = commandState.listed(it) },
                    { commandState = commandState.displayed(it) },
                    { message, clearCommands -> commandState = commandState.failed(message, clearCommands) }
                )
            } finally { commandState = commandState.completed() }
        }
    }

    fun refreshAll() {
        if (!CompanionRefreshLifecycle.canStart(refreshing, busy, benchmarkRunning, updating)) return
        refreshState = refreshState.started()
        operationModel.refreshOpenPanels()
        if (agentAssignmentsExpanded && operationModel.panels.panels.any { it.id == "agent-ops" })
            agentModel.refreshAssignments()
        val targetEndpoint = endpoint.trim()
        val targetToken = token
        scope.launch {
            CompanionRefreshLifecycle.run(
                work = { failures ->
                val client = try { ApiClient(targetEndpoint, targetToken) }
                    catch (e: Exception) {
                        failures.add("API settings: ${e.message}")
                        null
                    }
                if (client != null) {
                    suspend fun fetch(label: String, path: String, command: String? = null,
                                      args: JSONObject = JSONObject()): JSONObject? =
                        CompanionCommandActions.fetch(label, failures) {
                            withContext(Dispatchers.IO) { client.request(path, command, args) }
                        }
                    fetch("Health", "/api/v1/health")?.let { commandState = commandState.displayed(it.toString(2)) }
                    fetch("Quick status", "/api/v1/execute", "status-quick")?.let { commandState = commandState.displayed(it.toString(2)) }
                    fetch("Commands", "/api/v1/commands")?.let { response ->
                        val entries = response.getJSONArray("commands")
                        commandState = commandState.listed(ReadOnlyCommandCatalog.names(entries))
                    }

                }
                try {
                    updateState = updateState.status("Checking releases…")
                    update = withContext(Dispatchers.IO) { AppUpdater.check(installedCode) }
                    updateState = updateState.status(if (update == null) "App is up to date" else "Update available: ${update!!.version}")
                } catch (e: Exception) {
                    failures.add("App update: ${e.message}")
                    updateState = updateState.status("Update check failed: ${e.message}")
                }
                },
                onSummary = { refreshState = refreshState.copy(status = it) },
                onFinished = { refreshState = refreshState.copy(running = false) }
            )
        }
    }

    val benchmarkPanelContent: @Composable () -> Unit = {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Authenticated echo and read-only status · connected node", style = MaterialTheme.typography.bodySmall)
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
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
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

    var selectedModuleId by remember { mutableStateOf(ModuleRegistry.HOME) }
    var moduleFeedback by remember { mutableStateOf("") }
    val drawerState = rememberDrawerState(initialValue = DrawerValue.Closed)

    /**
     * A module switch owns the whole content region. Old in-flight operation
     * responses are invalidated by OperationViewModel.close, not displayed in
     * some other module. Navigation never invokes a mutating operation.
     */
    fun navigateToModule(id: String) {
        val destination = ModuleRegistry.get(id)?.destination ?: return
        if (destination !is ModuleDestination.Screen) {
            val intent = when (destination) {
                is ModuleDestination.HttpsLink -> Intent(Intent.ACTION_VIEW, Uri.parse(destination.url))
                is ModuleDestination.AndroidAppLink ->
                    Intent(Intent.ACTION_VIEW, Uri.parse(destination.url)).setPackage(destination.packageName)
                else -> return
            }
            try {
                context.startActivity(intent)
            } catch (_: android.content.ActivityNotFoundException) {
                moduleFeedback = "La aplicación externa no está disponible"
            } catch (_: SecurityException) {
                moduleFeedback = "No se puede abrir este módulo externo"
            }
            scope.launch { drawerState.close() }
            return
        }

        if (selectedModuleId != id) {
            if (FeatureRegistry.get(selectedModuleId)?.kind == FeatureKind.OPERATION) {
                operationModel.close(selectedModuleId)
            }
            localPanels = LocalPanelState()
            when {
                FeatureRegistry.get(id)?.kind == FeatureKind.OPERATION -> operationModel.open(id)
                id != "odoo-quotations" && LocalPanelState.isPanel(id) ->
                    localPanels = localPanels.open(id)
            }
            selectedModuleId = id
        }
        scope.launch { drawerState.close() }
    }

    BackHandler(enabled = drawerState.isOpen || selectedModuleId != ModuleRegistry.HOME) {
        if (drawerState.isOpen) scope.launch { drawerState.close() }
        else navigateToModule(ModuleRegistry.HOME)
    }

    val installedVersion = remember(context) {
        runCatching {
            @Suppress("DEPRECATION")
            context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: "unknown"
        }.getOrDefault("unknown")
    }
    val configuredHost = remember(endpoint, token) {
        if (token.isBlank()) "pendiente de token"
        else runCatching { java.net.URI(endpoint.trim()).host }.getOrNull() ?: "pendiente de configuración"
    }

    ModalNavigationDrawer(
        drawerState = drawerState,
        drawerContent = {
            ModuleDrawerContent(
                selectedId = selectedModuleId,
                updateAvailable = update != null,
                onSelect = ::navigateToModule
            )
        }
    ) {
        Scaffold(
            modifier = Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding(),
            topBar = {
                TopAppBar(
                    title = { Text(ModuleRegistry.get(selectedModuleId)?.label ?: "GWay Remote") },
                    navigationIcon = {
                        IconButton(onClick = { scope.launch { drawerState.open() } },
                            modifier = Modifier.semantics { contentDescription = "Abrir menú de módulos" }) {
                            Icon(Icons.Filled.Menu, contentDescription = null)
                        }
                    },
                    actions = {
                        if (FeatureRegistry.get(selectedModuleId)?.operation?.policy == ExecutionPolicy.AUTO_READ) {
                            IconButton(onClick = { operationModel.refresh(selectedModuleId) }) {
                                Icon(Icons.Filled.Refresh, contentDescription = "Actualizar módulo")
                            }
                        }
                    }
                )
            }
        ) { contentPadding ->
            Column(
                Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)
                    .padding(contentPadding).imePadding().verticalScroll(rememberScrollState())
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                when (selectedModuleId) {
                    ModuleRegistry.HOME -> ModuleHomePage(
                        installedVersion = installedVersion,
                        configuredEndpoint = configuredHost,
                        availableUpdate = update,
                        updateStatus = updateStatus,
                        updating = updating,
                        onOpenUpdate = { navigateToModule("app-update") },
                        onCheckUpdate = ::checkUpdates,
                        onOpenSettings = { navigateToModule(ModuleRegistry.SETTINGS) }
                    )
                    ModuleRegistry.SETTINGS -> ModuleSettingsPage(
                        settings = settings,
                        appearance = appearance,
                        onAppearanceChange = onAppearanceChange,
                        onEndpointChange = { settings = settings.copy(endpoint = it) },
                        onTokenChange = { settings = settings.copy(token = it) },
                        onSave = {
                            try {
                                ApiClient(endpoint.trim(), token)
                                store.endpoint = endpoint.trim()
                                store.token = token
                                settings = settings.saved()
                                moduleFeedback = "Configuración guardada"
                            } catch (e: Exception) {
                                moduleFeedback = e.message ?: "Configuración inválida"
                            }
                        },
                        feedback = moduleFeedback
                    )
                    "app-update" -> ModuleUpdatePage(
                        update = update,
                        updateStatus = updateStatus,
                        updating = updating,
                        apkReady = apk?.isFile == true,
                        onCheck = ::checkUpdates,
                        onDownload = ::downloadUpdate,
                        onInstall = ::requestInstall
                    )
                    "odoo-quotations" -> OdooQuotationsPanel(endpoint = endpoint, token = token)
                    "deployments", "mcp-access", "github-health" -> LocalPanelHost(
                        state = localPanels,
                        endpoint = endpoint,
                        token = token,
                        onClose = { navigateToModule(ModuleRegistry.HOME) },
                        onMove = { id, index -> localPanels = localPanels.move(id, index) }
                    )
                    else -> if (FeatureRegistry.get(selectedModuleId)?.kind == FeatureKind.OPERATION) {
                        // Only the selected operation exists in the content region.
                        OperationPalette(
                            state = panelState.copy(panels = panelState.panels.filter { it.id == selectedModuleId }),
                            onOpen = operationModel::open,
                            onClose = { navigateToModule(ModuleRegistry.HOME) },
                            onMove = operationModel::move,
                            onRefresh = operationModel::refresh,
                            onCsmsInspect = operationModel::inspectCsms,
                            csmsView = operationModel.csmsView,
                            onSelectCsmsView = operationModel::selectCsmsView,
                            apiHealth = operationModel.apiHealth,
                            systemStatus = operationModel.systemStatus,
                            onRefreshSystem = operationModel::refreshSystem,
                            agentAssignments = agentIssues,
                            agentInstance = agentModel.localAgent,
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
                            benchmarkContent = benchmarkPanelContent,
                            motifs = soundMotifs.available,
                            lcdNotification = operationModel.lcdNotification,
                            soundNotification = operationModel.soundNotification,
                            onNotificationInput = operationModel::notificationInput,
                            onExecuteNotification = operationModel::executeNotification,
                            onInput = operationModel::input,
                            onExecute = operationModel::execute,
                            showPalette = false
                        )
                    }
                }
                if (moduleFeedback.isNotBlank() && selectedModuleId != ModuleRegistry.SETTINGS) {
                    Text(moduleFeedback, color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}
