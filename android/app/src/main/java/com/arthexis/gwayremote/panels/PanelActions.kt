package com.arthexis.gwayremote

import androidx.compose.material3.*
import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.*

/** Shared policy-driven actions; specialized controls remain in the palette. */
@Composable
internal fun PanelActions(
    spec: OperationSpec,
    panel: OperationPanel,
    onRefresh: (String) -> Unit,
    onInput: (String, String, String) -> Unit,
    onExecute: (String, Map<String, String>) -> Unit
) {
    when (spec.policy) {
        ExecutionPolicy.AUTO_READ ->
            TextButton(onClick = { onRefresh(panel.id) }, enabled = !panel.loading) {
                Text("Refresh")
            }
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
