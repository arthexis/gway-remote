package com.arthexis.gwayremote

import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable

/**
 * Common actions driven by operation policy.
 * Mutating and parameterized operations retain their existing controls until
 * migrated explicitly; they must never execute through the read-only action.
 */
@Composable
internal fun PanelActions(
    spec: OperationSpec,
    panel: OperationPanel,
    onRefresh: (String) -> Unit
) {
    when (spec.policy) {
        ExecutionPolicy.AUTO_READ ->
            TextButton(
                onClick = { onRefresh(panel.id) },
                enabled = !panel.loading
            ) { Text("Refresh") }
        ExecutionPolicy.EXPLICIT_INPUT, ExecutionPolicy.CONFIRM -> Unit
    }
}
