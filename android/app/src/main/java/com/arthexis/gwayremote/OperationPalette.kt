package com.arthexis.gwayremote

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.material3.*
import androidx.compose.runtime.*
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
    benchmarkContent: @Composable () -> Unit,
    simulatorStatus: String,
    onSimulatorCommand: (String, JSONObject) -> Unit,
    onSelectSimulatorPeer: (String, String) -> Unit,
    onInspectTask: (String) -> Unit,
    agentSendLoading: Boolean,
    agentSendResult: String?,
    agentSendError: String?,
    onAgentSend: (String, String) -> Unit
) {
    var filter by remember { mutableStateOf("") }
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        state.panels.forEachIndexed { position, panel ->
            val spec = OperationRegistry.get(panel.id) ?: return@forEachIndexed
            OutlinedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(spec.label, style = MaterialTheme.typography.titleMedium)
                        Row {
                            if (position > 0) TextButton(onClick = { onMove(panel.id, position - 1) }) {
                                Text("↑")
                            }
                            if (position < state.panels.lastIndex) TextButton(onClick = { onMove(panel.id, position + 1) }) {
                                Text("↓")
                            }
                            IconButton(onClick = { onClose(panel.id) }) { Text("×") }
                        }
                    }
                    if (panel.loading) LinearProgressIndicator(Modifier.fillMaxWidth())
                    panel.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                    if (panel.id == "agent-ops") {
                        AgentOpsPanel(panel.output, agentSendLoading, agentSendResult, agentSendError, onAgentSend)
                    } else if (panel.id == "tasks") {
                        TaskHistoryPanel(panel.output, onInspectTask)
                    } else if (panel.id == "task-detail") {
                        TaskDetailPanel(panel.output)
                    } else if (panel.id == "simulator-results") {
                        SimulatorResultsPanel(panel.output)
                    } else if (panel.id == "simulator-status") {
                        SimulatorStatusPanel(panel.output)
                    } else if (panel.id == "csms") {
                        CsmsHealthPanel(panel.output)
                    } else if (panel.id == "csms-view") {
                        CsmsInspectionPanel(panel.output)
                    } else {
                        panel.output?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                    }
                    if (spec.policy == ExecutionPolicy.AUTO_READ) {
                        TextButton(onClick = { onRefresh(panel.id) }, enabled = !panel.loading) { Text("Refresh") }
                    } else if (panel.id == "task-detail") {
                        val taskId = panel.inputs["task_id"].orEmpty()
                        OutlinedTextField(taskId, { onInput(panel.id, "task_id", it) },
                            label = { Text("Task UUID") }, singleLine = true)
                        Button(enabled = !panel.loading && TASK_UUID.matches(taskId),
                            onClick = { onExecute(panel.id, mapOf("task_id" to taskId)) }) {
                            Text("Inspect task")
                        }
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
                            AlertDialog(onDismissRequest = { pending = null },
                                title = { Text("Confirm simulator operation") },
                                text = { Text("Execute $command on the configured simulator?") },
                                confirmButton = {
                                    TextButton(onClick = {
                                        pending = null
                                        onSimulatorCommand(command, args)
                                    }) { Text("Execute") }
                                },
                                dismissButton = {
                                    TextButton(onClick = { pending = null }) { Text("Cancel") }
                                })
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
                        val choices = listOf("ok", "notice", "attention", "warning", "error", "busy", "critical")
                        val sound = panel.inputs["sound"].orEmpty().ifEmpty { "notice" }
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
                        Button(enabled = !panel.loading && sound in choices,
                            onClick = { onExecute(panel.id, mapOf("sound" to sound)) }) {
                            Text("Play sound")
                        }
                    } else {
                        Text("Controls remain available in the existing interface until UI-4.",
                            style = MaterialTheme.typography.bodySmall)
                    }
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
                OutlinedButton(onClick = { onOpen(spec.id) }) {
                    Text(spec.label)
                }
            }
        }
    }
}

/** Interpret the existing read-command responses without modifying their API contracts. */
@Composable
private fun SimulatorStatusPanel(output: String?) {
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
private fun SimulatorResultsPanel(output: String?) {
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
private fun CsmsHealthPanel(output: String?) {
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
private fun CsmsInspectionPanel(output: String?) {
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

private val TASK_UUID = Regex("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

@Composable
private fun TaskHistoryPanel(output: String?, inspect: (String) -> Unit) {
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
private fun TaskDetailPanel(output: String?) {
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
private fun AgentOpsPanel(
    output: String?,
    sending: Boolean,
    sendResult: String?,
    sendError: String?,
    onSend: (String, String) -> Unit
) {
    var selectedRef by remember { mutableStateOf("") }
    var attempted by remember { mutableStateOf<Pair<String, String>?>(null) }
    val referencePattern = remember { Regex("[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}#[1-9][0-9]*") }
    OutlinedTextField(selectedRef, { selectedRef = it; attempted = null },
        label = { Text("GitHub issue OWNER/REPO#N") }, singleLine = true)
    val valid = referencePattern.matches(selectedRef)
    Button(enabled = valid && !sending, onClick = {
        val timestamp = java.time.Instant.now().truncatedTo(java.time.temporal.ChronoUnit.SECONDS).toString()
        attempted = selectedRef to timestamp
        onSend(selectedRef, timestamp)
    }) { Text("Send issue") }
    if (sending) LinearProgressIndicator(Modifier.fillMaxWidth())
    if (sendError != null) {
        Text("Submission not confirmed: $sendError", color = MaterialTheme.colorScheme.error)
        val pending = attempted
        if (pending != null) {
            TextButton(enabled = !sending, onClick = { onSend(pending.first, pending.second) }) {
                Text("Retry same submission")
            }
        }
    }
    if (sendResult != null) Text("Agent response: $sendResult", style = MaterialTheme.typography.bodySmall)

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
                val entries = issues.optJSONArray("issues")
                if (entries == null) Text("Issue list unavailable", style = MaterialTheme.typography.bodySmall)
                else if (entries.length() == 0) Text("No issues reported")
                else for (index in 0 until entries.length()) {
                    val issue = entries.optJSONObject(index) ?: continue
                    Text("#${issue.optString("number", "?")} ${issue.optString("title", "Untitled issue")}")
                    val issueRef = "${issue.optString("repository") }#${issue.optInt("number")}"
                    if (referencePattern.matches(issueRef)) {
                        TextButton(onClick = { selectedRef = issueRef; attempted = null }) { Text("Select for Send") }
                    }
                    Text("${issue.optString("repository", "")} · ${issue.optString("state", "unknown")} · ${issue.optInt("comment_count", issue.optInt("comments", 0))} comments",
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
        val status = data.optJSONObject("status")
        if (status == null) Text("Agent status unavailable")
        else {
            // Do not infer remaining budget percentages from unspecified CLI fields.
            Text("5-hour remaining: unavailable")
            Text("Weekly remaining: unavailable")
            var expanded by remember { mutableStateOf(false) }
            TextButton(onClick = { expanded = !expanded }) {
                Text(if (expanded) "Hide status JSON" else "Show status JSON")
            }
            if (expanded) Text(status.toString(2), style = MaterialTheme.typography.bodySmall)
        }
    }
}
