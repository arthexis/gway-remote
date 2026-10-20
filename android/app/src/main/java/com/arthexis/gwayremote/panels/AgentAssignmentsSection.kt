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
    localAgent: String,
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
    val targetPattern = remember { Regex("^gway-[0-9]+$") }
    val availableLabels = issues.flatMap { issue ->
        val labels = issue.optJSONArray("labels")
        (0 until (labels?.length() ?: 0)).mapNotNull { index ->
            labels?.optString(index)?.takeIf { it.isNotBlank() }
        }
    }.toSet()
    val instances = (availableLabels.filter { targetPattern.matches(it) } +
        localAgent.takeIf { targetPattern.matches(it) }.orEmpty())
        .filter { it.isNotBlank() }.distinct().sorted()
    val otherLabels = availableLabels.filterNot { targetPattern.matches(it) }.sorted()
    var instanceFilter by remember { mutableStateOf("") }
    var labelFilter by remember { mutableStateOf("") }
    LaunchedEffect(localAgent) {
        if (localAgent.isNotBlank() && instanceFilter.isBlank()) instanceFilter = localAgent
    }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Box(Modifier.weight(1f)) {
            var expandedInstances by remember { mutableStateOf(false) }
            OutlinedButton(
                onClick = { expandedInstances = true },
                modifier = Modifier.fillMaxWidth()
            ) { Text(when (instanceFilter) { "", "*" -> "All instances"; "-" -> "Unassigned"; else -> instanceFilter },
                     maxLines = 1) }
            DropdownMenu(expanded = expandedInstances,
                         onDismissRequest = { expandedInstances = false }) {
                DropdownMenuItem(text = { Text("All instances") }, onClick = {
                    instanceFilter = "*"; expandedInstances = false
                })
                DropdownMenuItem(text = { Text("Unassigned") }, onClick = {
                    instanceFilter = "-"; expandedInstances = false
                })
                instances.forEach { name ->
                    DropdownMenuItem(text = { Text(name) }, onClick = {
                        instanceFilter = name; expandedInstances = false
                    })
                }
            }
        }
        Box(Modifier.weight(1f)) {
            var expandedLabels by remember { mutableStateOf(false) }
            OutlinedButton(onClick = { expandedLabels = true },
                           modifier = Modifier.fillMaxWidth()) {
                Text(if (labelFilter.isBlank()) "All labels" else labelFilter, maxLines = 1)
            }
            DropdownMenu(expanded = expandedLabels,
                         onDismissRequest = { expandedLabels = false }) {
                DropdownMenuItem(text = { Text("All labels") }, onClick = {
                    labelFilter = ""; expandedLabels = false
                })
                otherLabels.forEach { name ->
                    DropdownMenuItem(text = { Text(name) }, onClick = {
                        labelFilter = name; expandedLabels = false
                    })
                }
            }
        }
    }
    val visibleIssues = issues.filter { issue ->
        val labels = issue.optJSONArray("labels")
        val names = (0 until (labels?.length() ?: 0)).map { labels!!.optString(it) }.toSet()
        val instanceMatches = when (instanceFilter) {
            "*", "" -> true
            "-" -> names.none { targetPattern.matches(it) }
            else -> instanceFilter in names
        }
        instanceMatches && (labelFilter.isBlank() || labelFilter in names)
    }
    Text("${visibleIssues.size} of ${issues.size} issues", style = MaterialTheme.typography.bodySmall)
    visibleIssues.forEach { issue ->
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
