package com.arthexis.gwayremote

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
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
    val scope = rememberCoroutineScope()

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
                        if (item.optBoolean("read_only") && item.optJSONObject("arguments")?.length() == 0)
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
        Text("GWay Remote", style = MaterialTheme.typography.headlineMedium)
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
                result = "Connection settings saved"
            } catch (e: Exception) { result = e.message ?: "Invalid settings" }
        }) { Text("Save settings") }
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
