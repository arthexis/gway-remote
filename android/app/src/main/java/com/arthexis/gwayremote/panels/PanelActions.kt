package com.arthexis.gwayremote

import androidx.compose.material3.*
import androidx.compose.runtime.Composable

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
