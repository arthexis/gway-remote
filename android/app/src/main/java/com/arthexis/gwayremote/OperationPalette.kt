package com.arthexis.gwayremote

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext
import android.content.Context
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.net.Uri
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import org.json.JSONObject

/**
 * UI-3: presentation only. UI-4 will migrate full parameterized
 * operations. Existing controls remain accessible during transition.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun OperationPalette(
    state: OperationPanelState,
    onOpen: (String) -> Unit,
    onClose: (String) -> Unit,
    onMove: (String, Int) -> Unit,
    onRefresh: (String) -> Unit,
    onInput: (String, String, String) -> Unit,
    onExecute: (String, Map<String, String>) -> Unit,
    motifs: List<String>,
    benchmarkContent: @Composable () -> Unit,
    simulatorStatus: String,
    onSimulatorCommand: (String, JSONObject) -> Unit,
    onSelectSimulatorPeer: (String, String) -> Unit,
    onInspectTask: (String) -> Unit,
    agentSendLoading: Boolean,
    agentSendResult: String?,
    agentSendError: String?,
    onAgentSend: (String, String) -> Unit,
    onAgentCopyPrompt: (String) -> Unit,
    agentObserveLoading: Boolean,
    agentObserveResult: String?,
    agentObserveError: String?,
    onAgentObserve: (String, String) -> Unit
) {
    var filter by remember { mutableStateOf("") }
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        state.panels.forEachIndexed { position, panel ->
            val spec = OperationRegistry.get(panel.id) ?: return@forEachIndexed
            StandardPanel(
                spec = spec,
                panel = panel,
                position = position,
                panelCount = state.panels.size,
                onMove = onMove,
                onClose = onClose
            ) {
                    PanelContent(
                        panel = panel,
                        onInspectTask = onInspectTask,
                        agentSendLoading = agentSendLoading,
                        agentSendResult = agentSendResult,
                        agentSendError = agentSendError,
                        onAgentSend = onAgentSend,
                        onAgentCopyPrompt = onAgentCopyPrompt,
                        agentObserveLoading = agentObserveLoading,
                        agentObserveResult = agentObserveResult,
                        agentObserveError = agentObserveError,
                        onAgentObserve = onAgentObserve
                    )
                    PanelActions(spec = spec, panel = panel, onRefresh = onRefresh, onInput = onInput, onExecute = onExecute)
                    if (spec.policy == ExecutionPolicy.AUTO_READ || panel.id == "task-detail") {
                        // Common read and task-detail actions are rendered by PanelActions.
                    } else if (panel.id == "simulator-discover") {
                        val discovered = remember(panel.output) {
                            runCatching {
                                val peers = JSONObject(panel.output ?: "{}").optJSONObject("result")
                                    ?.optJSONArray("peers")
                                if (peers == null) emptyList<String>()
                                else (0 until peers.length()).mapNotNull { index ->
                                    peers.optJSONObject(index)?.optString("host")
                                        ?.takeIf { it.isNotBlank() }
                                }.distinct()
                            }.getOrDefault(emptyList())
                        }
                        if (discovered.isNotEmpty()) {
                            Text("Discovered Ethernet peers: ${discovered.size}")
                            discovered.forEach { peer ->
                                OutlinedButton(onClick = {
                                    onSelectSimulatorPeer(peer, panel.inputs["port"] ?: "9000")
                                }) { Text("Use $peer for Start") }
                            }
                        }

                        val host = panel.inputs["host"].orEmpty()
                        val port = panel.inputs["port"] ?: "9000"
                        OutlinedTextField(host, { onInput(panel.id, "host", it) },
                            label = { Text("Ethernet target (optional)") }, singleLine = true)
                        OutlinedTextField(port, { onInput(panel.id, "port", it) },
                            label = { Text("CSMS port") }, singleLine = true)
                        Button(
                            enabled = !panel.loading && port.toIntOrNull()?.let { it in 1..65535 } == true,
                            onClick = { onExecute(panel.id, mapOf("host" to host, "port" to port)) }
                        ) { Text("Discover / check target") }
                    } else if (panel.id == "benchmark") {
                        benchmarkContent()
                    } else if (panel.id == "simulator-start" || panel.id == "simulator-stop") {
                        val host = panel.inputs["host"].orEmpty()
                        val port = panel.inputs["port"] ?: "9000"
                        var pending by remember(panel.id) { mutableStateOf<Pair<String, JSONObject>?>(null) }
                        if (panel.id == "simulator-start") {
                            OutlinedTextField(host, { onInput(panel.id, "host", it) },
                                label = { Text("Ethernet target host") }, singleLine = true)
                            OutlinedTextField(port, { onInput(panel.id, "port", it) },
                                label = { Text("CSMS port") }, singleLine = true)
                            // Reuse the original validated scenarios and payload builder;
                            // avoid duplicating its charging parameter contract.
                            SimulatorControls(host, port, simulatorStatus, panel.loading) { command, args ->
                                pending = command to args
                            }
                        } else {
                            Text("Simulator: $simulatorStatus")
                            Button(enabled = !panel.loading && simulatorStatus.startsWith("running"),
                                onClick = { pending = "simulator-stop" to JSONObject() }) {
                                Text("Stop simulation")
                            }
                        }
                        pending?.let { (command, args) ->
                            ConfirmPanelAction(
                                title = "Confirm simulator operation",
                                description = "Execute $command on the configured simulator?",
                                onConfirm = {
                                    pending = null
                                    onSimulatorCommand(command, args)
                                },
                                onCancel = { pending = null }
                            )
                        }
                    } else if (panel.id == "csms-view") {
                        val views = listOf("status", "chargers", "charge-points", "transactions",
                            "events", "alerts", "rfid-report", "report")
                        val selected = panel.inputs["view"] ?: "status"
                        var menuOpen by remember(panel.id) { mutableStateOf(false) }
                        Box {
                            OutlinedButton(onClick = { menuOpen = true }) {
                                Text("View: $selected ▾")
                            }
                            DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                                views.forEach { view ->
                                    DropdownMenuItem(text = { Text(view) }, onClick = {
                                        onInput(panel.id, "view", view)
                                        menuOpen = false
                                    })
                                }
                            }
                        }
                        Button(enabled = !panel.loading && selected in views,
                            onClick = { onExecute(panel.id, mapOf("view" to selected)) }) {
                            Text("Inspect")
                        }
                    } else if (panel.id == "lcd") {
                        val line1 = panel.inputs["line1"].orEmpty()
                        val line2 = panel.inputs["line2"].orEmpty()
                        val duration = panel.inputs["duration"].orEmpty().ifEmpty { "30" }
                        OutlinedTextField(line1, { next ->
                            if (next.length <= 16 && next.all { it.code in 32..126 }) onInput(panel.id, "line1", next)
                        }, label = { Text("LCD line 1 (max 16)") }, singleLine = true)
                        OutlinedTextField(line2, { next ->
                            if (next.length <= 16 && next.all { it.code in 32..126 }) onInput(panel.id, "line2", next)
                        }, label = { Text("LCD line 2 (max 16)") }, singleLine = true)
                        OutlinedTextField(duration, { onInput(panel.id, "duration", it) },
                            label = { Text("Duration (30–300 seconds)") }, singleLine = true)
                        Button(
                            enabled = !panel.loading && (line1.isNotEmpty() || line2.isNotEmpty()) &&
                                (duration.toIntOrNull()?.let { it in 30..300 } == true),
                            onClick = { onExecute(panel.id, panel.inputs + ("duration" to duration)) }
                        ) { Text("Show on LCD") }
                    } else if (panel.id == "sound") {
                        var expanded by remember(panel.id) { mutableStateOf(false) }
                        var motifExpanded by remember(panel.id) { mutableStateOf(false) }
                        val choices = listOf("ok", "notice", "attention", "warning", "error", "busy", "critical")
                        val sound = panel.inputs["sound"].orEmpty().ifEmpty { "notice" }
                        val motif = panel.inputs["motif"].orEmpty()
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Box {
                            OutlinedButton(onClick = { motifExpanded = true }) {
                                Text("Motif: ${motif.ifEmpty { "None" }} ▾")
                            }
                            DropdownMenu(expanded = motifExpanded, onDismissRequest = { motifExpanded = false }) {
                                (listOf("") + motifs).distinct().forEach { name ->
                                    DropdownMenuItem(text = { Text(name.ifEmpty { "None" }) }, onClick = {
                                        onInput(panel.id, "motif", name)
                                        motifExpanded = false
                                    })
                                }
                            }
                        }
                        Box {
                            OutlinedButton(onClick = { expanded = true }) { Text("Sound: $sound ▾") }
                            DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                                choices.forEach { name ->
                                    DropdownMenuItem(text = { Text(name) }, onClick = {
                                        onInput(panel.id, "sound", name)
                                        expanded = false
                                    })
                                }
                            }
                        }
                        }
                        Button(enabled = !panel.loading && sound in choices && (motif.isEmpty() || motif in motifs),
                            onClick = { onExecute(panel.id, mapOf("sound" to sound, "motif" to motif)) }) {
                            Text("Play sound")
                        }
                    } else {
                        Text("Controls remain available in the existing interface until UI-4.",
                            style = MaterialTheme.typography.bodySmall)
                    }
            }
        }
        OutlinedTextField(
            value = filter, onValueChange = { filter = it },
            label = { Text("Filter operations") }, singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp)) {
            state.unopened(filter).forEach { spec ->
                OperationButton(spec = spec, onOpen = onOpen)
            }
        }
    }
}

/** Interpret the existing read-command responses without modifying their API contracts. */
@Composable
internal fun SimulatorStatusPanel(output: String?) {
    if (output == null) return
    val result = remember(output) { runCatching { JSONObject(output).optJSONObject("result") }.getOrNull() }
    if (result == null) {
        Text(output, style = MaterialTheme.typography.bodySmall)
        return
    }
    Text("State: ${result.optString("state", "unknown")}")
    Text("Target: ${result.optString("target", "unknown")}")
}

@Composable
internal fun SimulatorResultsPanel(output: String?) {
    if (output == null) {
        Text("Refresh to load captured simulator results.", style = MaterialTheme.typography.bodySmall)
        return
    }
    val result = remember(output) { runCatching { JSONObject(output).optJSONObject("result") }.getOrNull() }
    if (result == null) {
        Text(output, style = MaterialTheme.typography.bodySmall)
        return
    }
    val log = result.optString("output", "")
    val truncated = result.optBoolean("truncated", false)
    Text("Process: ${result.optString("state", "unknown")} — ${result.optString("target", "unknown")}")
    Text("Outcome: ${result.optString("outcome", "unknown")}" +
        (if (result.has("exit_code") && !result.isNull("exit_code"))
            " (exit ${result.optInt("exit_code")})" else ""))
    if (truncated) Text("Output truncated to last 32 KB", color = MaterialTheme.colorScheme.error)
    Text("OCPP activity", style = MaterialTheme.typography.titleSmall)
    val milestones = remember(log, truncated) { SimulatorActivitySummary.parse(log, truncated) }
    if (milestones.isEmpty()) Text("No recognizable OCPP milestones in captured output.")
    else milestones.forEach { milestone ->
        Text("${milestone.label}: ${milestone.evidence}", style = MaterialTheme.typography.bodySmall)
    }
    var rawExpanded by remember { mutableStateOf(false) }
    TextButton(onClick = { rawExpanded = !rawExpanded }) {
        Text(if (rawExpanded) "Hide raw output" else "Show raw output")
    }
    if (rawExpanded) Text(if (log.isEmpty()) "No output captured" else log,
        style = MaterialTheme.typography.bodySmall)
}

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
internal fun CsmsInspectionPanel(output: String?) {
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
    Text(if (content.isBlank()) "No inspection output returned" else content,
        style = MaterialTheme.typography.bodySmall)
}

internal val TASK_UUID = Regex("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

@Composable
internal fun TaskHistoryPanel(output: String?, inspect: (String) -> Unit) {
    if (output == null) return
    val tasks = remember(output) {
        runCatching { JSONObject(output).optJSONObject("result")?.optJSONArray("tasks") }.getOrNull()
    }
    if (tasks == null) {
        Text("Task history unavailable", color = MaterialTheme.colorScheme.error)
        return
    }
    if (tasks.length() == 0) Text("No recorded tasks")
    for (index in 0 until tasks.length()) {
        val entry = tasks.optJSONObject(index) ?: continue
        val task = entry.optJSONObject("task") ?: continue
        val execution = entry.optJSONObject("execution")
        val id = task.optString("id")
        val state = task.optString("state", "unknown")
        val result = execution?.optString("status")?.takeIf { it.isNotBlank() }
        Text("Task ${id.take(8)} · $state" + (result?.let { " · $it" } ?: ""))
        val issue = task.optString("issue_number")
        val repository = task.optString("repository")
        if (repository.isNotBlank() && issue.isNotBlank()) Text("$repository#$issue",
            style = MaterialTheme.typography.bodySmall)
        if (TASK_UUID.matches(id)) TextButton(onClick = { inspect(id) }) { Text("Inspect details") }
        HorizontalDivider()
    }
}

@Composable
internal fun TaskDetailPanel(output: String?) {
    if (output == null) return
    val result = remember(output) {
        runCatching { JSONObject(output).optJSONObject("result") }.getOrNull()
    }
    if (result == null) {
        Text("Task details unavailable", color = MaterialTheme.colorScheme.error)
        return
    }
    val task = result.optJSONObject("task")
    val execution = result.optJSONObject("execution")
    Text("Task: ${task?.optString("id", "unknown") ?: "unknown"}")
    Text("State: ${task?.optString("state", "unknown") ?: "unknown"}")
    Text("Execution: ${execution?.optString("status", "not recorded") ?: "not recorded"}")
    execution?.optString("summary")?.takeIf { it.isNotBlank() }?.let { Text(it) }
    var showRaw by remember { mutableStateOf(false) }
    TextButton(onClick = { showRaw = !showRaw }) {
        Text(if (showRaw) "Hide JSON" else "Show JSON")
    }
    if (showRaw) Text(result.toString(2), style = MaterialTheme.typography.bodySmall)
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
        TextButton(enabled = !observing && !sending, onClick = {
            onObserve(attempted.first, attempted.second)
        }) { Text("Check submission") }
        if (sendError != null) {
            TextButton(enabled = !sending, onClick = { onSend(attempted.first, attempted.second) }) {
                Text("Retry same submission")
            }
        }
    }
    if (observing) LinearProgressIndicator(Modifier.fillMaxWidth())
    if (observationError != null) Text("Observation unavailable: $observationError")
    if (observation != null) Text("Observation: $observation", style = MaterialTheme.typography.bodySmall)
    if (sendResult != null) Text("Request response: $sendResult", style = MaterialTheme.typography.bodySmall)

    if (output == null) return
    val data = remember(output) {
        runCatching { JSONObject(output).optJSONObject("result") }.getOrNull()
    }
    if (data == null) {
        Text("Agent Ops response unavailable", color = MaterialTheme.colorScheme.error)
        return
    }
    Text("Issues", style = MaterialTheme.typography.titleSmall)
    if (data.has("issues_error")) {
        Text("Unavailable: ${data.optString("issues_error")}", color = MaterialTheme.colorScheme.error)
    } else {
        val issues = data.opt("issues")
        when (issues) {
            is JSONObject -> {
                val entries = issues.optJSONObject("data")?.optJSONArray("issues")
                if (entries == null) Text("Issue list unavailable", style = MaterialTheme.typography.bodySmall)
                else if (entries.length() == 0) Text("No issues reported")
                else for (index in 0 until entries.length()) {
                    val issue = entries.optJSONObject(index) ?: continue
                    val issueRef = "${issue.optString("repository")}#${issue.optInt("number")}"
                    val issueUrl = issue.optString("url")
                    val expectedUrl = if (referencePattern.matches(issueRef))
                        "https://github.com/${issue.optString("repository")}/issues/${issue.optInt("number")}" else ""
                    val validUrl = expectedUrl.isNotEmpty() && issueUrl == expectedUrl
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
                        Button(enabled = validUrl && !sending, onClick = { confirmRef = issueRef }) { Text("Send to Agent") }
                        OutlinedButton(enabled = validUrl, onClick = { onCopyPrompt(issueRef) }) { Text("Copy Prompt") }
                    }
                    Text("${issue.optString("repository", "")} · ${agentIssueState(issue)} · ${issue.optInt("comments", 0)} comments",
                        style = MaterialTheme.typography.bodySmall)
                }
            }
            else -> Text("Issue list unavailable", style = MaterialTheme.typography.bodySmall)
        }
    }
    HorizontalDivider()
    Text("Agent status and budgets", style = MaterialTheme.typography.titleSmall)
    if (data.has("status_error")) {
        Text("Unavailable: ${data.optString("status_error")}", color = MaterialTheme.colorScheme.error)
    } else {
        val status = data.optJSONObject("status")?.optJSONObject("data")
        if (status == null) Text("Agent status unavailable")
        else {
            val budget = status.optJSONObject("budget")
            AgentBudgetWindow("5-hour", budget?.optJSONObject("five_hour"))
            AgentBudgetWindow("Weekly", budget?.optJSONObject("weekly"))
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

@Composable
private fun AgentBudgetWindow(label: String, window: JSONObject?) {
    val percent = window?.opt("remaining_percent")
    val available = window?.optBoolean("available", false) == true &&
        percent is Number && percent.toDouble() in 0.0..100.0
    val remaining = if (available) "${percent}%" else "unavailable"
    Text("$label remaining: $remaining")
    if (available) {
        window?.optString("resets_at")?.takeIf { it.isNotBlank() && it != "null" }
            ?.let { Text("Resets: $it", style = MaterialTheme.typography.bodySmall) }
    }
}
