package com.arthexis.gwayremote

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/**
 * Shared shell for all operation panels. Operation-specific inputs and results
 * are provided as content; execution policies remain in the controller.
 */
@Composable
fun StandardPanel(
    spec: OperationSpec,
    panel: OperationPanel,
    position: Int,
    panelCount: Int,
    onMove: (String, Int) -> Unit,
    onClose: (String) -> Unit,
    content: @Composable ColumnScope.() -> Unit
) {
    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(spec.label, style = MaterialTheme.typography.titleMedium)
                Row {
                    if (position > 0) {
                        TextButton(onClick = { onMove(panel.id, position - 1) }) { Text("↑") }
                    }
                    if (position < panelCount - 1) {
                        TextButton(onClick = { onMove(panel.id, position + 1) }) { Text("↓") }
                    }
                    IconButton(onClick = { onClose(panel.id) }) { Text("×") }
                }
            }
            if (panel.loading) LinearProgressIndicator(Modifier.fillMaxWidth())
            panel.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            content()
        }
    }
}
