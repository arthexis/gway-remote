package com.arthexis.gwayremote

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

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
    onExecute: (String, Map<String, String>) -> Unit
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
                    panel.output?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                    if (spec.policy == ExecutionPolicy.AUTO_READ) {
                        TextButton(onClick = { onRefresh(panel.id) }, enabled = !panel.loading) { Text("Refresh") }
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
