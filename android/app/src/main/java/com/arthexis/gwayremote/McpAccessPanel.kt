package com.arthexis.gwayremote

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch

/** Optional administrative UI: no token, grant or passkey material in disk state. */
@Composable
internal fun McpAccessPanel(onClose: () -> Unit) {
    val activity = LocalContext.current as ComponentActivity
    val scope = rememberCoroutineScope()
    var enabled by remember { mutableStateOf(false) }
    var loading by remember { mutableStateOf(true) }
    var busy by remember { mutableStateOf(false) }
    var principal by remember { mutableStateOf("") }
    var grant by remember { mutableStateOf("") }
    var revokeId by remember { mutableStateOf("") }
    var issuedId by remember { mutableStateOf("") }
    var bearer by remember { mutableStateOf("") }
    var status by remember { mutableStateOf("") }

    // Android screenshot and recent-apps previews must never capture secrets.
    DisposableEffect(activity.window) {
        val originallySecure = activity.window.attributes.flags and
            WindowManager.LayoutParams.FLAG_SECURE != 0
        activity.window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        onDispose {
            bearer = ""
            grant = ""
            if (!originallySecure) {
                activity.window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
            }
        }
    }
    LaunchedEffect(Unit) {
        enabled = McpPasskeyClient.available()
        loading = false
    }
    fun runSafely(action: suspend () -> Unit) {
        if (busy || !enabled || !McpPasskeyClient.validPrincipal(principal)) return
        busy = true
        bearer = ""
        status = ""
        scope.launch {
            try {
                action()
            } catch (_: Exception) {
                // Never render server payloads, raw assertions or bearer in errors.
                status = "Operation not completed. Verify Watchtower access and passkey."
            } finally {
                busy = false
            }
        }
    }

    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        HorizontalDivider()
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("MCP Access", style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.weight(1f))
            TextButton(onClick = onClose) { Text("Close") }
        }
        Text("Watchtower passkey authentication is required for each sensitive action.")
        Text(if (loading) "Checking administrative access…"
            else if (enabled) "Passkey issuer available"
            else "Unavailable: issuer disabled or device origin not approved.")
        if (!enabled) return@Column
        OutlinedTextField(value = principal, onValueChange = { principal = it },
            label = { Text("Administrator ID") }, singleLine = true,
            modifier = Modifier.fillMaxWidth(), enabled = !busy)
        OutlinedTextField(value = grant, onValueChange = { grant = it },
            label = { Text("One-use enrollment grant") }, singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            modifier = Modifier.fillMaxWidth(), enabled = !busy)
        OutlinedButton(enabled = !busy && grant.length in 32..128 &&
            McpPasskeyClient.validPrincipal(principal), onClick = {
            val singleUse = grant
            grant = ""
            runSafely {
                McpPasskeyClient.enroll(activity, principal, singleUse)
                status = "Passkey enrolled. Enrollment grant consumed."
            }
        }) { Text("Enroll passkey") }
        HorizontalDivider()
        Button(enabled = !busy && McpPasskeyClient.validPrincipal(principal),
            onClick = { runSafely {
                val issued = McpPasskeyClient.issue(activity, principal)
                issuedId = issued.first
                bearer = issued.second
                status = "New bearer issued. Copy it once; it will not be recoverable."
            } }) { Text("Issue read + execute bearer") }
        if (bearer.isNotEmpty()) {
            Text("Bearer ID: $issuedId")
            OutlinedTextField(value = bearer, onValueChange = {},
                readOnly = true, visualTransformation = PasswordVisualTransformation(),
                modifier = Modifier.fillMaxWidth(), label = { Text("New bearer · shown once") })
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = {
                    val manager = activity.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                    manager.setPrimaryClip(ClipData.newPlainText("GWay MCP bearer", bearer))
                    bearer = ""
                    status = "Copied to Android clipboard. Paste promptly, then clear clipboard."
                }) { Text("Copy once") }
                TextButton(onClick = { bearer = ""; status = "Bearer hidden" }) {
                    Text("Hide")
                }
            }
        }
        HorizontalDivider()
        OutlinedTextField(value = revokeId, onValueChange = { revokeId = it },
            label = { Text("Bearer ID to revoke (24 hexadecimal characters)") },
            modifier = Modifier.fillMaxWidth(), singleLine = true, enabled = !busy)
        OutlinedButton(enabled = !busy && Regex("[0-9a-f]{24}").matches(revokeId) &&
            McpPasskeyClient.validPrincipal(principal), onClick = { runSafely {
            val id = revokeId
            val revoked = McpPasskeyClient.revoke(activity, principal, id)
            revokeId = ""
            issuedId = ""
            status = if (revoked) "Bearer revoked" else "Bearer already absent or revoked"
        } }) { Text("Revoke bearer with passkey") }
        if (busy) Text("Waiting for passkey verification…")
        if (status.isNotBlank()) Text(status)
    }
}
