package com.arthexis.gwayremote

import android.os.Bundle
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import androidx.compose.ui.platform.LocalContext
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
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
        window.decorView.systemUiVisibility = 0
        window.setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE)
        val store = SecretStore(this)
        setContent { MaterialTheme { CompanionScreen(store) } }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun CompanionScreen(store: SecretStore) {
    var endpoint by remember { mutableStateOf(store.endpoint) }
    var token by remember { mutableStateOf(store.token) }
    var result by remember { mutableStateOf("Configure HTTPS endpoint and token") }
    var commands by remember { mutableStateOf(listOf<String>()) }
    var busy by remember { mutableStateOf(false) }
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
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val installedCode = if (android.os.Build.VERSION.SDK_INT >= 33)
        context.packageManager.getPackageInfo(context.packageName, android.content.pm.PackageManager.PackageInfoFlags.of(0)).longVersionCode
    else @Suppress("DEPRECATION") context.packageManager.getPackageInfo(context.packageName, 0).longVersionCode
    var update by remember { mutableStateOf<AvailableUpdate?>(null) }
    var updateStatus by remember { mutableStateOf("") }
    var updating by remember { mutableStateOf(false) }
    var apk by remember { mutableStateOf<java.io.File?>(null) }

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
            try {
                apk = withContext(Dispatchers.IO) { AppUpdater.download(context, candidate) }
                updateStatus = "Verified; confirm installation in Android"
                AppUpdater.install(context, apk!!)
            } catch (e: Exception) { updateStatus = e.message ?: "Update failed" }
            finally { updating = false }
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

    Column(Modifier.fillMaxSize().imePadding().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text("GWay Remote", style = MaterialTheme.typography.headlineMedium)
            IconButton(onClick = { settingsOpen = !settingsOpen },
                modifier = Modifier.semantics { contentDescription = "API settings" }) {
                Text("⚙", style = MaterialTheme.typography.headlineMedium)
            }
        }
        if (update != null && !settingsOpen) {
            Text("Update available: ${update!!.version}")
            Button(enabled = !updating, onClick = { downloadUpdate() }) { Text("Update app") }
        }
        if (settingsOpen) {
            HorizontalDivider()
            Text("App updates", style = MaterialTheme.typography.titleMedium)
            Button(enabled = !updating, onClick = { checkUpdates() }) { Text("Check for updates") }
            if (update != null) {
                Button(enabled = !updating, onClick = { downloadUpdate() }) { Text("Download update") }
            }
            if (apk != null) {
                OutlinedButton(onClick = {
                    try { AppUpdater.install(context, apk!!) }
                    catch (e: Exception) { updateStatus = e.message ?: "Installation failed" }
                }) { Text("Install downloaded update") }
            }
            if (updateStatus.isNotBlank()) Text(updateStatus)
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
