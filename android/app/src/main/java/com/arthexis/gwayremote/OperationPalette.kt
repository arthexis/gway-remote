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
    onSimulatorCommand: (String, JSONObject) -> Unit
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
                    if (panel.id == "simulator-results") {
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
                    } else if (panel.id == "simulator-discover") {
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
