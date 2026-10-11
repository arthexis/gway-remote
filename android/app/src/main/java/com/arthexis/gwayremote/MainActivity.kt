package com.arthexis.gwayremote

import android.os.Bundle
import androidx.compose.ui.platform.LocalContext
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.ui.graphics.Color
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
    var lcdLine1 by remember { mutableStateOf("") }
    var lcdLine2 by remember { mutableStateOf("") }
    var lcdDuration by remember { mutableFloatStateOf(30f) }
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
                result = response.toString(2)
            } catch (e: Exception) {
                result = e.message ?: "Connection failed"
                if (path.endsWith("/commands")) commands = emptyList()
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
        Text("LCD (16 × 2)", style = MaterialTheme.typography.titleMedium)
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
        Text("Manual sound", style = MaterialTheme.typography.titleMedium)
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
        Text("Available read-only operations", style = MaterialTheme.typography.titleMedium)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp)) {
        commands.forEach { name ->
            OutlinedButton(enabled = !busy, onClick = { perform("/api/v1/execute", name) }) {
                Text(name)
            }
        }
        }
        if (busy) LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        Text("Response", style = MaterialTheme.typography.titleMedium)
        Text(result)
        Spacer(Modifier.height(LocalConfiguration.current.screenHeightDp.dp / 2))
    }
}
