package com.arthexis.gwayremote

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.util.UUID

/** Manual deployment control; polling never dispatches. */
@Composable
fun DeploymentsPanel(endpoint: String, token: String) {
    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences("deployment-follow", 0) }
    val targets = listOf("all", "ocpp-csms", "ocpp-reports", "ocpp-simulator",
        "gway-agent-ops", "gway-ap-kiosk", "gway-rfid", "gway-lcd-sound", "gway-bastion")
    var selected by remember { mutableStateOf("all") }
    var expanded by remember { mutableStateOf(false) }
    var confirm by remember { mutableStateOf(false) }
    var requestId by remember { mutableStateOf(prefs.getString("request_id", "") ?: "") }
    var overview by remember { mutableStateOf<JSONObject?>(null) }
    var follow by remember { mutableStateOf<JSONObject?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var refresh by remember { mutableIntStateOf(0) }
    var dispatchNonce by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(endpoint, token, refresh) {
        if (endpoint.isBlank() || token.isBlank()) return@LaunchedEffect
        try {
            val response = withContext(Dispatchers.IO) {
                ApiClient(endpoint.trim(), token).request("/api/v1/execute", "deployments-overview")
            }
            overview = response.optJSONObject("result")
            error = null
        } catch (e: Exception) { error = e.message ?: "Overview unavailable" }
    }
    LaunchedEffect(endpoint, token, requestId, refresh) {
        if (requestId.isBlank() || endpoint.isBlank() || token.isBlank()) return@LaunchedEffect
        while (isActive) {
            try {
                val response = withContext(Dispatchers.IO) {
                    ApiClient(endpoint.trim(), token).request("/api/v1/execute", "deployments-follow",
                        JSONObject().put("request_id", requestId))
                }
                follow = response.optJSONObject("result")
                error = null
            } catch (e: Exception) { error = e.message ?: "Follow unavailable" }
            val state = follow?.optString("state")
            if (state == "completed") break
            delay(4000)
        }
    }
    LaunchedEffect(dispatchNonce) {
        val nonce = dispatchNonce ?: return@LaunchedEffect
        busy = true
        try {
            withContext(Dispatchers.IO) {
                ApiClient(endpoint.trim(), token).request("/api/v1/execute", "deployments-dispatch",
                    JSONObject().put("target", selected).put("request_id", nonce).put("confirm", true))
            }
            requestId = nonce
            prefs.edit().putString("request_id", nonce).apply()
            follow = null
            confirm = false
            error = null
        } catch (e: Exception) {
            // HTTP failures may be ambiguous: preserve the request ID to observe, never resend.
            requestId = nonce
            prefs.edit().putString("request_id", nonce).apply()
            error = e.message ?: "Submission unconfirmed; check Follow"
        } finally { busy = false; dispatchNonce = null }
    }
    Column(verticalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
        Text("Deployments · GWAY-001", style = MaterialTheme.typography.titleMedium)
        val controller = overview?.optJSONObject("controller")
        Text("GWAY Remote server (automatic)", style = MaterialTheme.typography.labelLarge)
        Text("Updated: " + (controller?.optString("last_successful_update")?.takeIf { it.isNotBlank() && it != "null" } ?: "Unknown"))
        Text("Revision: " + (controller?.optString("installed_sha")?.takeIf { it.isNotBlank() && it != "null" }?.take(12) ?: "Unknown"))
        ExposedDropdownMenuBox(expanded = expanded, onExpandedChange = { expanded = it }) {
            OutlinedTextField(value = selected, onValueChange = {}, readOnly = true,
                label = { Text("Repository") }, trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded) },
                modifier = Modifier.fillMaxWidth().menuAnchor())
            ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                targets.forEach { target ->
                    DropdownMenuItem(text = { Text(if (target == "all") "All repositories" else target) },
                        onClick = { selected = target; confirm = false; expanded = false })
                }
            }
        }
        Row { Checkbox(checked = confirm, onCheckedChange = { confirm = it });
            Text("Confirm deployment of " + (if (selected == "all") "all repositories" else selected)) }
        Button(onClick = { dispatchNonce = UUID.randomUUID().toString().replace("-", "") },
            enabled = confirm && !busy && requestId.isBlank(), modifier = Modifier.fillMaxWidth()) {
            Text(if (busy) "Requesting…" else "Deploy " + selected)
        }
        OutlinedButton(onClick = { refresh++ }) { Text("Refresh") }
        if (requestId.isNotBlank()) {
            Text("Following request " + requestId.take(12), style = MaterialTheme.typography.labelMedium)
            Text("State: " + (follow?.optString("state") ?: "Unconfirmed"))
            val rows = follow?.optJSONArray("repositories")
            if (rows != null) for (index in 0 until rows.length()) {
                val row = rows.optJSONObject(index) ?: continue
                Text(row.optString("name") + " · " + row.optString("state") +
                    " · " + row.optString("conclusion", "—"))
                val events = row.optJSONArray("diagnostic_tail")
                if (events != null) for (j in 0 until events.length())
                    Text("  " + events.optString(j), style = MaterialTheme.typography.bodySmall)
            }
            if (follow?.optString("state") == "completed")
                OutlinedButton(onClick = { requestId = ""; follow = null;
                    prefs.edit().remove("request_id").apply() }) { Text("Start new deployment") }
        }
        if (error != null) Text(error!!, color = MaterialTheme.colorScheme.error)
    }
}
