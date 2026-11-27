package com.arthexis.gwayremote.features.deployments

import com.arthexis.gwayremote.*
import com.arthexis.gwayremote.ui.components.ModuleHeader
import com.arthexis.gwayremote.ui.components.ModuleLoading
import com.arthexis.gwayremote.ui.components.ModuleNotice
import com.arthexis.gwayremote.ui.components.ModuleActions
import com.arthexis.gwayremote.ui.components.ModuleSectionTitle

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.selection.toggleable
import androidx.compose.ui.semantics.Role
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.testTagsAsResourceId
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
    // A saved confirmation must not become a latent dispatch authorization
    // after endpoint or credentials are changed elsewhere in the app.
    LaunchedEffect(endpoint, token) { confirm = false }
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
        ModuleHeader("Deployments", "GWAY-001 · Seguimiento y despacho explícito")
        val controller = overview?.optJSONObject("controller")
        ModuleSectionTitle("GWAY Remote server (automatic)")
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
        DeploymentConfirmation(selected, confirm) { confirm = it }
        if (endpoint.isBlank() || token.isBlank()) {
            ModuleNotice("Configura el endpoint HTTPS y el token antes de desplegar.", isError = true)
        }
        DeploymentSubmitButton(
            selected = selected, confirmed = confirm,
            endpoint = endpoint, token = token, busy = busy, requestId = requestId
        ) {
            // UI and ViewModel independently enforce the same dispatch prerequisites.
            val id = UUID.randomUUID().toString().replace("-", "")
            model.dispatch(selected, id) { submitted ->
                prefs.edit().putString("request_id", submitted).apply()
            }
            confirm = false
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
        ModuleNotice(error, isError = true)
    }
}

/** Whole 48dp+ row is an accessible checkbox target; entering the screen never confirms. */
@OptIn(ExperimentalComposeUiApi::class)
@Composable
internal fun DeploymentConfirmation(selected: String, checked: Boolean, onCheckedChange: (Boolean) -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth()
            .toggleable(value = checked, role = Role.Checkbox, onValueChange = onCheckedChange)
            .testTag("rc-deploy-confirm").semantics { testTagsAsResourceId = true }
            .heightIn(min = 48.dp),
        verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Checkbox(checked = checked, onCheckedChange = null)
        Text("Confirm deployment of " + (if (selected == "all") "all repositories" else selected))
    }
}


/** Pure UI gate; the ViewModel independently rejects unauthenticated dispatches. */
internal fun canRequestDeployment(
    confirmed: Boolean, endpoint: String, token: String, busy: Boolean, requestId: String
): Boolean = confirmed && endpoint.isNotBlank() && token.isNotBlank() &&
    !busy && requestId.isBlank()

/** Callback is never invoked on entry or when credentials are absent. */
@OptIn(ExperimentalComposeUiApi::class)
@Composable
internal fun DeploymentSubmitButton(
    selected: String,
    confirmed: Boolean,
    endpoint: String,
    token: String,
    busy: Boolean,
    requestId: String,
    onDispatch: () -> Unit
) {
    val allowed = canRequestDeployment(confirmed, endpoint, token, busy, requestId)
    Button(
        onClick = { if (allowed) onDispatch() },
        enabled = allowed,
        modifier = Modifier.fillMaxWidth().testTag("rc-deploy-submit").semantics { testTagsAsResourceId = true }
    ) {
        Text(if (busy) "Requesting…" else "Deploy " + selected)
    }
}
