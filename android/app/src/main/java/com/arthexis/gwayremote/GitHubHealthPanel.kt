package com.arthexis.gwayremote

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

private val allowedRepos = listOf(
    "arthexis/ocpp-csms", "arthexis/gway-remote", "arthexis/ocpp-simulator",
    "arthexis/gway-rfid", "arthexis/gway-ap-kiosk"
)

@Composable
fun GitHubHealthPanel(endpoint: String, token: String) {
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    var snapshot by remember { mutableStateOf<JSONObject?>(null) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var filter by remember { mutableStateOf("All") }
    var showResolved by remember { mutableStateOf(false) }

    fun refresh() {
        if (loading) return
        if (endpoint.isBlank() || token.isBlank()) {
            snapshot = null
            error = "Configure the API endpoint and token"
            return
        }
        loading = true
        scope.launch {
            try {
                val response = withContext(Dispatchers.IO) {
                    ApiClient(endpoint.trim(), token).request("/api/v1/github-health")
                }
                snapshot = response
                error = null
            } catch (e: Exception) {
                snapshot = null
                error = e.message ?: "Health report unavailable"
            } finally {
                loading = false
            }
        }
    }

    LaunchedEffect(endpoint, token) { refresh() }

    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("GitHub Health · cached hourly watch", style = MaterialTheme.typography.titleMedium)
        Text("Read-only. Refresh does not run checks or deploy.", style = MaterialTheme.typography.bodySmall)
        OutlinedButton(onClick = { refresh() }, enabled = !loading) {
            Text(if (loading) "Loading…" else "Refresh report")
        }
        if (error != null) Text("Unavailable: $error", color = MaterialTheme.colorScheme.error)
        val data = snapshot
        if (data != null) {
            if (data.optString("status") != "available") {
                Text("Unavailable: " + data.optString("reason", "No completed watch"),
                    color = MaterialTheme.colorScheme.error)
            } else {
                Text("Last completed: " + data.optString("completed_at"))
                if (data.optString("classification_status") == "not_implemented") {
                    Text("Evidence only — alert classification is not yet available.",
                        color = MaterialTheme.colorScheme.error)
                }
                val repos = data.optJSONArray("repositories")
                val names = if (repos == null) emptySet() else
                    (0 until repos.length()).mapNotNull { repos.optJSONObject(it)?.optString("name") }.toSet()
                if (names != allowedRepos.toSet()) {
                    Text("Incomplete or unexpected repository scope", color = MaterialTheme.colorScheme.error)
                } else {
                    val alerts = data.optJSONArray("alerts")
                    val entries = if (alerts == null) emptyList() else
                        (0 until alerts.length()).mapNotNull { alerts.optJSONObject(it) }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        FilterChip(selected = !showResolved, onClick = { showResolved = false },
                            label = { Text("Active") })
                        FilterChip(selected = showResolved, onClick = { showResolved = true },
                            label = { Text("Resolved") })
                    }
                    // Keep the selector compact; no additional GitHub requests.
                    val choices = listOf("All") + allowedRepos
                    choices.chunked(2).forEach { chunk ->
                        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                            chunk.forEach { repo ->
                                FilterChip(selected = filter == repo, onClick = { filter = repo },
                                    label = { Text(if (repo == "All") repo else repo.substringAfter('/')) })
                            }
                        }
                    }
                    val visible = entries.filter {
                        it.optString("state") == (if (showResolved) "RESOLVED" else "ACTIVE") &&
                            (filter == "All" || it.optString("repository") == filter)
                    }
                    if (visible.isEmpty()) Text("No recorded alerts in this view")
                    visible.forEach { alert ->
                        ElevatedCard(Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                Text(alert.optString("title", "Alert"), style = MaterialTheme.typography.titleSmall)
                                Text(alert.optString("repository") + " · " + alert.optString("category"))
                                if (showResolved) Text("Resolution: " + alert.optString("resolution_kind", "unspecified"))
                                else Text(alert.optString("next_action", "See evidence"))
                                val url = alert.optString("evidence_url")
                                if (url.startsWith("https://github.com/")) {
                                    TextButton(onClick = {
                                        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                                    }) { Text("Open in GitHub") }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
