package com.arthexis.gwayremote

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import org.json.JSONObject
import java.util.UUID

/** Manual deployment control; polling never dispatches. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DeploymentsPanel(endpoint: String, token: String) {
    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences("deployment-follow", 0) }
    val targets = listOf("all", "ocpp-csms", "ocpp-reports",
        "gway-agent-ops", "gway-ap-kiosk", "gway-rfid", "gway-lcd-sound", "gway-bastion")
    var selected by remember { mutableStateOf("all") }
    var expanded by remember { mutableStateOf(false) }
    var confirm by remember { mutableStateOf(false) }
    val model: DeploymentsViewModel = viewModel()
    val restoredId = prefs.getString("request_id", "") ?: ""
    LaunchedEffect(endpoint, token, restoredId) {
        model.connect(endpoint, token, restoredId)
    }
    val requestId = model.requestId
    val overview = model.overview
    val follow = model.follow
    val error = model.error
    val busy = model.busy
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
        Button(onClick = {
            if (confirm) {
                val id = UUID.randomUUID().toString().replace("-", "")
                model.dispatch(selected, id) { submitted ->
                    prefs.edit().putString("request_id", submitted).apply()
                }
                confirm = false
            }
        },
            enabled = confirm && !busy && requestId.isBlank(), modifier = Modifier.fillMaxWidth()) {
            Text(if (busy) "Requesting…" else "Deploy " + selected)
        }
        OutlinedButton(onClick = { model.refresh() }) { Text("Refresh") }
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
                OutlinedButton(onClick = { model.clear { prefs.edit().remove("request_id").apply() } }) { Text("Start new deployment") }
        }
        if (error != null) Text(error!!, color = MaterialTheme.colorScheme.error)
    }
}
