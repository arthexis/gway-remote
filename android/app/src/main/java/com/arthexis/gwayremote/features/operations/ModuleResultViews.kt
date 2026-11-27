package com.arthexis.gwayremote.features.operations

import com.arthexis.gwayremote.*
import com.arthexis.gwayremote.ui.components.ModulePage
import com.arthexis.gwayremote.ui.components.ModuleHeader
import com.arthexis.gwayremote.ui.components.ModuleLoading
import com.arthexis.gwayremote.ui.components.ModuleNotice
import com.arthexis.gwayremote.ui.components.ModuleSectionTitle

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
import androidx.compose.ui.unit.dp
import org.json.JSONObject

/** Specialized module results, independent of the former operation palette. */
@Composable
internal fun CsmsHealthPanel(output: String?) {
    if (output == null) {
        Text("CSMS health not yet checked", style = MaterialTheme.typography.bodySmall)
        return
    }
    val result = remember(output) { runCatching { JSONObject(output).optJSONObject("result") }.getOrNull() }
    if (result == null) {
        Text("CSMS health response unavailable", color = MaterialTheme.colorScheme.error)
        return
    }
    val healthy = if (result.has("healthy") && !result.isNull("healthy"))
        result.optBoolean("healthy") else null
    Text(when (healthy) {
        true -> "Healthy"
        false -> "Needs attention"
        null -> "Health unknown"
    })
    Text(result.optString("reason").ifBlank { "No diagnostic details" },
        style = MaterialTheme.typography.bodySmall)
}

@Composable
internal fun CsmsInspectionPanel(output: String?, view: String = "status") {
    if (output == null) return
    val result = remember(output) { runCatching { JSONObject(output).optJSONObject("result") }.getOrNull() }
    if (result == null) {
        Text("Inspection response unavailable", color = MaterialTheme.colorScheme.error)
        return
    }
    if (result.optBoolean("truncated", false)) {
        Text("Output truncated to 64 KB", color = MaterialTheme.colorScheme.error)
    }
    val content = result.optString("output", "")
    CsmsCompactInspection(view, content)
}

@Composable
internal fun AgentOpsPanel(
    output: String?,
    sending: Boolean,
    sendResult: String?,
    sendError: String?,
    onSend: (String, String) -> Unit,
    onCopyPrompt: (String) -> Unit,
    observing: Boolean,
    observation: String?,
    observationError: String?,
    onObserve: (String, String) -> Unit
) {
    val context = LocalContext.current
    val prefs = remember(context) { context.getSharedPreferences("agent-ops-submission", Context.MODE_PRIVATE) }
    var attemptedRef by remember { mutableStateOf(prefs.getString("ref", "").orEmpty()) }
    var attemptedAt by remember { mutableStateOf(prefs.getString("at", "").orEmpty()) }
    // Persist the server-confirmed identity, not only the locally proposed time.
    LaunchedEffect(sendResult) {
        val receipt = sendResult?.let { runCatching { JSONObject(it) }.getOrNull() }
        val data = receipt?.optJSONObject("data")
        val canonicalRef = data?.optString("issue", "").orEmpty()
        val canonicalAt = data?.optString("at", "").orEmpty()
        if (canonicalRef.isNotBlank() && canonicalAt.isNotBlank()) {
            attemptedRef = canonicalRef
            attemptedAt = canonicalAt
            prefs.edit().putString("ref", canonicalRef).putString("at", canonicalAt).apply()
        }
    }
    val attempted = if (attemptedRef.isNotBlank() && attemptedAt.isNotBlank()) attemptedRef to attemptedAt else null
    val referencePattern = remember { Regex("[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}#[1-9][0-9]*") }
    var confirmRef by remember { mutableStateOf<String?>(null) }
    confirmRef?.let { ref ->
        AlertDialog(onDismissRequest = { confirmRef = null },
            title = { Text("Send to Agent?") },
            text = { Text("Request execution of $ref? This does not confirm completion.") },
            confirmButton = { TextButton(onClick = {
                confirmRef = null
                val at = java.time.Instant.now().truncatedTo(java.time.temporal.ChronoUnit.SECONDS).toString()
                attemptedRef = ref
                attemptedAt = at
                prefs.edit().putString("ref", ref).putString("at", at).apply()
                onSend(ref, at)
            }) { Text("Send to Agent") } },
            dismissButton = { TextButton(onClick = { confirmRef = null }) { Text("Cancel") } })
    }
    if (sending) LinearProgressIndicator(Modifier.fillMaxWidth())
    if (sendError != null) {
        Text("Submission not confirmed: $sendError", color = MaterialTheme.colorScheme.error)
    }
    if (attempted != null) {
        Text("Last requested: ${attempted.first} · ${attempted.second}", style = MaterialTheme.typography.bodySmall)
        if (sendError != null) {
            TextButton(enabled = !sending, onClick = { onSend(attempted.first, attempted.second) }) {
                Text("Retry same submission")
            }
        }
    }
    if (attempted != null) {
        val status = observation?.let(AgentSubmissionStatus::parse)
        val statusLabel = when {
            observing -> "Checking status…"
            status != null -> status.label
            sendError != null -> "Submission unconfirmed"
            sending -> "Submitting…"
            sendResult != null -> "Submission response received"
            else -> "Awaiting verification"
        }
        val statusColor = when (status) {
            AgentSubmissionStatus.FINISHED -> MaterialTheme.colorScheme.primary
            AgentSubmissionStatus.CODEX_FAILED, AgentSubmissionStatus.INTERRUPTED ->
                MaterialTheme.colorScheme.error
            AgentSubmissionStatus.REQUESTED, AgentSubmissionStatus.ACCEPTED,
            AgentSubmissionStatus.RELEASED -> MaterialTheme.colorScheme.tertiary
            else -> MaterialTheme.colorScheme.onSurfaceVariant
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Agent Ops:", style = MaterialTheme.typography.labelMedium)
            Text(statusLabel, color = statusColor, style = MaterialTheme.typography.labelMedium)
        }
        Text(
            if (status?.terminal == true) "Execution outcome reported by Agent Ops"
            else "Submission does not confirm execution; use Check submission to verify",
            style = MaterialTheme.typography.bodySmall
        )
    }
    if (observing) LinearProgressIndicator(Modifier.fillMaxWidth())
    if (observationError != null) Text("Observation unavailable: $observationError",
        color = MaterialTheme.colorScheme.error)
    var showResponse by remember(sendResult) { mutableStateOf(false) }
    if (attempted != null || sendResult != null) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (attempted != null) {
                TextButton(enabled = !observing && !sending, onClick = {
                    onObserve(attempted.first, attempted.second)
                }) { Text("Check submission") }
            }
            if (sendResult != null) {
                TextButton(onClick = { showResponse = !showResponse }) {
                    Text(if (showResponse) "Hide response" else "Show response")
                }
            }
        }
        if (showResponse && sendResult != null) Text(sendResult, style = MaterialTheme.typography.bodySmall)
    }

    if (output == null) return
    val data = remember(output) {
        runCatching { JSONObject(output).optJSONObject("result") }.getOrNull()
    }
    if (data == null) {
        Text("Agent Ops response unavailable", color = MaterialTheme.colorScheme.error)
        return
    }
    ModuleSectionTitle("Issues")
    if (data.has("issues_error")) {
        Text("Unavailable: ${data.optString("issues_error")}", color = MaterialTheme.colorScheme.error)
    } else {
        val issues = data.opt("issues")
        when (issues) {
            is JSONObject -> {
                val issueData = issues.optJSONObject("data")
                val entries = issueData?.optJSONArray("issues")
                if (entries == null) Text("Issue list unavailable", style = MaterialTheme.typography.bodySmall)
                else {
                    val localAgent = issueData?.optString("agent", "")?.lowercase().orEmpty()
                    val instancePattern = remember { Regex("^gway-[0-9]{3}$") }
                    val rows = (0 until entries.length()).mapNotNull { entries.optJSONObject(it) }
                    fun labels(row: JSONObject): Set<String> = agentIssueLabels(row)
                    val allLabels = rows.flatMap { labels(it) }.toSet()
                    val instances = (allLabels.filter { instancePattern.matches(it) } +
                        listOf(localAgent).filter { instancePattern.matches(it) }).distinct().sorted()
                    val categories = allLabels.filterNot { instancePattern.matches(it) }.sorted()
                    var instanceFilter by remember(localAgent) { mutableStateOf("*") }
                    var categoryFilter by remember { mutableStateOf("") }
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Box(Modifier.weight(1f)) {
                            var open by remember { mutableStateOf(false) }
                            OutlinedButton(onClick = { open = true }, modifier = Modifier.fillMaxWidth()) {
                                Text(when (instanceFilter) {
                                    "*" -> "All assignments"
                                    "-" -> "Unassigned"
                                    "" -> "Assignment unavailable"
                                    else -> instanceFilter
                                }, maxLines = 1)
                            }
                            DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
                                DropdownMenuItem(text = { Text("All assignments") }, onClick = {
                                    instanceFilter = "*"; open = false
                                })
                                DropdownMenuItem(text = { Text("Unassigned") }, onClick = {
                                    instanceFilter = "-"; open = false
                                })
                                instances.forEach { name ->
                                    DropdownMenuItem(text = { Text(name) }, onClick = {
                                        instanceFilter = name; open = false
                                    })
                                }
                            }
                        }
                        Box(Modifier.weight(1f)) {
                            var open by remember { mutableStateOf(false) }
                            OutlinedButton(onClick = { open = true }, modifier = Modifier.fillMaxWidth()) {
                                Text(if (categoryFilter.isBlank()) "All labels" else categoryFilter,
                                    maxLines = 1)
                            }
                            DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
                                DropdownMenuItem(text = { Text("All labels") }, onClick = {
                                    categoryFilter = ""; open = false
                                })
                                categories.forEach { name ->
                                    DropdownMenuItem(text = { Text(name) }, onClick = {
                                        categoryFilter = name; open = false
                                    })
                                }
                            }
                        }
                    }
                    val visible = rows.filter { row ->
                        val names = labels(row)
                        val instanceMatch = agentIssueMatchesInstance(row, instanceFilter)
                        instanceMatch && (categoryFilter.isBlank() || categoryFilter in names)
                    }
                    Text("${visible.size} of ${rows.size} issues",
                         style = MaterialTheme.typography.bodySmall)
                    for (issue in visible) {
                    val issueRef = "${issue.optString("repository")}#${issue.optInt("number")}"
                    val issueUrl = issue.optString("url")
                    val expectedUrl = if (referencePattern.matches(issueRef))
                        "https://github.com/${issue.optString("repository")}/issues/${issue.optInt("number")}" else ""
                    val validUrl = expectedUrl.isNotEmpty() && issueUrl == expectedUrl
                    // A cached projection is advisory; Agent Ops independently
                    // rechecks trusted issue eligibility before submission and execution.
                    val eligible = agentIssueEligible(issue)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        TextButton(enabled = validUrl, onClick = {
                            runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(issueUrl))) }
                        }, modifier = Modifier.weight(1f)) {
                            Text("#${issue.optInt("number")} ${issue.optString("title", "Untitled issue")}")
                        }
                        IconButton(enabled = validUrl, onClick = {
                            val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                            clipboard.setPrimaryClip(ClipData.newPlainText("GitHub issue", issueUrl))
                        }) { Text("⧉") }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(enabled = validUrl && eligible && !sending, onClick = { confirmRef = issueRef }) { Text("Send to Agent") }
                        OutlinedButton(enabled = validUrl, onClick = { onCopyPrompt(issueRef) }) { Text("Copy Prompt") }
                    }
                    if (!eligible) {
                        Text("Not eligible for manual execution; check the issue state and AgentOps eligibility.",
                            color = MaterialTheme.colorScheme.error,
                            style = MaterialTheme.typography.bodySmall)
                    }
                    Text("${issue.optString("repository", "")} · ${agentIssueState(issue)} · ${issue.optInt("comments", 0)} comments",
                        style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
            else -> Text("Issue list unavailable", style = MaterialTheme.typography.bodySmall)
        }
    }
    HorizontalDivider()
    ModuleSectionTitle("Agent status and budgets")
    if (data.has("status_error")) {
        Text("Unavailable: ${data.optString("status_error")}", color = MaterialTheme.colorScheme.error)
    } else {
        val status = data.optJSONObject("status")?.optJSONObject("data")
        if (status == null) Text("Agent status unavailable")
        else {
            val budget = status.optJSONObject("budget")
            Text("5h: ${agentBudgetRemaining(budget?.optJSONObject("five_hour"))}  ·  Weekly: ${agentBudgetRemaining(budget?.optJSONObject("weekly"))}", style = MaterialTheme.typography.bodySmall)
            var expanded by remember { mutableStateOf(false) }
            TextButton(onClick = { expanded = !expanded }) {
                Text(if (expanded) "Hide status JSON" else "Show status JSON")
            }
            if (expanded) Text(status.toString(2), style = MaterialTheme.typography.bodySmall)
        }
    }
}

private fun agentIssueState(issue: JSONObject): String {
    return when (issue.optString("state", "").lowercase()) {
        "open" -> "Open"
        "attended" -> "Attended"
        "sent" -> {
            val sent = issue.optString("sent_at")
            val elapsed = runCatching {
                java.time.Duration.between(java.time.Instant.parse(sent), java.time.Instant.now()).seconds
            }.getOrNull()
            val age = when {
                elapsed == null || elapsed < 0 -> null
                elapsed < 60 -> "${elapsed}s"
                elapsed < 3600 -> "${elapsed / 60}m"
                elapsed < 86400 -> "${elapsed / 3600}h"
                else -> "${elapsed / 86400}d"
            }
            if (age == null) "Sent" else "Sent $age"
        }
        else -> "Unknown"
    }
}

private fun agentBudgetRemaining(window: JSONObject?): String {
    val percent = window?.opt("remaining_percent")
    val available = window?.optBoolean("available", false) == true &&
        percent is Number && percent.toDouble() in 0.0..100.0
    val remaining = if (available) "${percent}%" else "unavailable"
    val reset = window?.optString("resets_at")?.takeIf { available && it.isNotBlank() && it != "null" }
    return if (reset == null) remaining else "$remaining (resets $reset)"
}

/** Normalize the canonical Agent Ops label projection without treating object labels as missing. */
internal fun agentIssueLabels(issue: JSONObject): Set<String> {
    val values = issue.optJSONArray("labels") ?: return emptySet()
    return (0 until values.length()).mapNotNull { index ->
        when (val value = values.opt(index)) {
            is String -> value
            is JSONObject -> value.optString("name", "")
            else -> null
        }?.trim()?.takeIf { it.isNotEmpty() }
    }.toSet()
}

/** Filter automatic-assignment labels only; manual eligibility is independent. */
internal fun agentIssueMatchesInstance(issue: JSONObject, selected: String): Boolean {
    val instancePattern = Regex("^gway-[0-9]{3}$")
    val labels = agentIssueLabels(issue)
    return when (selected) {
        "*" -> true
        "-" -> labels.none { instancePattern.matches(it) }
        "" -> false
        else -> selected in labels && instancePattern.matches(selected)
    }
}
