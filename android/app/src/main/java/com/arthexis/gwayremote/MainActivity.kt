package com.arthexis.gwayremote

import android.os.Bundle
import androidx.compose.ui.platform.LocalContext
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val store = SecretStore(this)
        setContent { MaterialTheme { CompanionScreen(store) } }
    }
}

@Composable
fun CompanionScreen(store: SecretStore) {
    var endpoint by remember { mutableStateOf(store.endpoint) }
    var token by remember { mutableStateOf(store.token) }
    var result by remember { mutableStateOf("Configure HTTPS endpoint and token") }
    var commands by remember { mutableStateOf(listOf<String>()) }
    var busy by remember { mutableStateOf(false) }
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

    fun perform(path: String, command: String? = null) {
        if (busy) return
        busy = true
        scope.launch {
            try {
                val response = withContext(Dispatchers.IO) {
                    ApiClient(endpoint.trim(), token).request(path, command)
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

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
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
        Text("Available read-only operations", style = MaterialTheme.typography.titleMedium)
        commands.forEach { name ->
            OutlinedButton(enabled = !busy, onClick = { perform("/api/v1/execute", name) }) {
                Text(name)
            }
        }
        if (busy) LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        Text("Response", style = MaterialTheme.typography.titleMedium)
        Text(result)
    }
}
