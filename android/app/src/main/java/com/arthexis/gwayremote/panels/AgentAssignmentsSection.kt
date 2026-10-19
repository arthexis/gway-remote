package com.arthexis.gwayremote

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import org.json.JSONObject

/** Retains the legacy codex-issues assignment reader inside the unified Agent Ops card. */
@Composable
internal fun AgentAssignmentsSection(
    issues: List<JSONObject>,
    loading: Boolean,
    error: String,
    onRefresh: () -> Unit,
    onError: (String) -> Unit,
    expanded: Boolean,
    onExpandedChange: (Boolean) -> Unit
) {
    val context = LocalContext.current
    OutlinedButton(onClick = {
        onExpandedChange(!expanded)
        if (!expanded) onRefresh()
    }) { Text(if (expanded) "Hide assignments" else "Assignments") }
    if (!expanded) return
    if (loading) LinearProgressIndicator(Modifier.fillMaxWidth())
    if (error.isNotBlank()) Text(error, color = MaterialTheme.colorScheme.error)
    issues.forEach { issue ->
        val url = issue.optString("url")
        val state = issue.optString("state", "queued")
        val sent = issue.optString("sent_at")
        val status = when (state) {
            "sent" -> {
                val elapsed = try {
                    val start = java.time.OffsetDateTime.parse(sent).toInstant()
                    java.time.Duration.between(start, java.time.Instant.now()).seconds.coerceAtLeast(0)
                } catch (_: Exception) { 0L }
                "Sent " + when {
                    elapsed < 60 -> "${elapsed}s"
                    elapsed < 3600 -> "${elapsed / 60}m"
                    elapsed < 86400 -> "${elapsed / 3600}h"
                    else -> "${elapsed / 86400}d"
                }
            }
            "attended" -> "Attended"
            else -> "Queued"
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Column(Modifier.weight(1f)) {
                TextButton(onClick = {
                    try { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }
                    catch (_: Exception) { onError("Unable to open GitHub") }
                }) { Text("#${issue.optInt("number")} ${issue.optString("title")}") }
                Text("${issue.optString("repository")} · $status", style = MaterialTheme.typography.bodySmall)
            }
            Text("☏ ${issue.optInt("comments")}", modifier = Modifier.padding(top = 12.dp))
            IconButton(onClick = {
                val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                clipboard.setPrimaryClip(ClipData.newPlainText("GitHub issue", url))
            }, modifier = Modifier.semantics { contentDescription = "Copy issue URL" }) { Text("↗") }
        }
        HorizontalDivider()
    }
}
