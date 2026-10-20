package com.arthexis.gwayremote

import androidx.compose.material3.*
import androidx.compose.foundation.layout.*
import androidx.compose.ui.unit.dp
import androidx.compose.runtime.*

/** Shared policy-driven actions; specialized controls remain in the palette. */
@Composable
internal fun PanelActions(
    spec: OperationSpec,
    panel: OperationPanel,
    onRefresh: (String) -> Unit,
    onInput: (String, String, String) -> Unit,
    onExecute: (String, Map<String, String>) -> Unit,
    motifs: List<String>
) {
    when (spec.policy) {
        ExecutionPolicy.AUTO_READ -> Unit // Pull-to-refresh owns safe reads.
        ExecutionPolicy.EXPLICIT_INPUT -> {
            if (panel.id == "task-detail") {
                val taskId = panel.inputs["task_id"].orEmpty()
                OutlinedTextField(
                    value = taskId,
                    onValueChange = { onInput(panel.id, "task_id", it) },
                    label = { Text("Task UUID") },
                    singleLine = true
                )
                Button(
                    enabled = !panel.loading && TASK_UUID.matches(taskId),
                    onClick = { onExecute(panel.id, mapOf("task_id" to taskId)) }
                ) { Text("Inspect task") }
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
                Button(
                    enabled = !panel.loading && selected in views,
                    onClick = { onExecute(panel.id, mapOf("view" to selected)) }
                ) { Text("Inspect") }
            } else if (panel.id == "lcd") {
                val line1 = panel.inputs["line1"].orEmpty()
                val line2 = panel.inputs["line2"].orEmpty()
                val duration = panel.inputs["duration"].orEmpty().ifEmpty { "30" }
                OutlinedTextField(
                    value = line1,
                    onValueChange = { next ->
                        if (LcdInput.validLine(next)) {
                            onInput(panel.id, "line1", next)
                        }
                    },
                    label = { Text("LCD line 1 (max 16)") },
                    singleLine = true
                )
                OutlinedTextField(
                    value = line2,
                    onValueChange = { next ->
                        if (next.length <= 16 && next.all { it.code in 32..126 }) {
                            onInput(panel.id, "line2", next)
                        }
                    },
                    label = { Text("LCD line 2 (max 16)") },
                    singleLine = true
                )
                OutlinedTextField(
                    value = duration,
                    onValueChange = { onInput(panel.id, "duration", it) },
                    label = { Text("Duration (30–300 seconds)") },
                    singleLine = true
                )
                Button(
                    enabled = LcdInput.canExecute(panel.inputs, panel.loading),
                    onClick = {
                        onExecute(panel.id, LcdInput.payload(panel.inputs))
                    }
                ) { Text("Show on LCD") }
            } else if (panel.id == "sound") {
                var soundExpanded by remember(panel.id) { mutableStateOf(false) }
                var motifExpanded by remember(panel.id) { mutableStateOf(false) }
                val sound = SoundInput.sound(panel.inputs)
                val motif = SoundInput.motif(panel.inputs)
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
                        OutlinedButton(onClick = { soundExpanded = true }) {
                            Text("Sound: $sound ▾")
                        }
                        DropdownMenu(expanded = soundExpanded, onDismissRequest = { soundExpanded = false }) {
                            SoundInput.choices.forEach { name ->
                                DropdownMenuItem(text = { Text(name) }, onClick = {
                                    onInput(panel.id, "sound", name)
                                    soundExpanded = false
                                })
                            }
                        }
                    }
                }
                Button(
                    enabled = SoundInput.canExecute(panel.inputs, motifs, panel.loading),
                    onClick = { onExecute(panel.id, SoundInput.payload(panel.inputs)) }
                ) { Text("Play sound") }
            }
        }
        ExecutionPolicy.CONFIRM -> Unit // Specialized confirmation controls migrate separately.
    }
}

/** Shared confirmation presentation; the caller owns pending action state. */
@Composable
internal fun ConfirmPanelAction(
    title: String,
    description: String,
    onConfirm: () -> Unit,
    onCancel: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onCancel,
        title = { Text(title) },
        text = { Text(description) },
        confirmButton = { TextButton(onClick = onConfirm) { Text("Execute") } },
        dismissButton = { TextButton(onClick = onCancel) { Text("Cancel") } }
    )
}
