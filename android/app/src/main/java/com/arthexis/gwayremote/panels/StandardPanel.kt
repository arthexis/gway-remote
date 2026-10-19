package com.arthexis.gwayremote

import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.Close
import androidx.compose.ui.Alignment
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
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top
            ) {
                Text(
                    spec.label,
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.weight(1f).padding(top = 4.dp)
                )
                Row(
                    horizontalArrangement = Arrangement.spacedBy(0.dp),
                    verticalAlignment = Alignment.Top
                ) {
                    if (position > 0) {
                        IconButton(onClick = { onMove(panel.id, position - 1) }) {
                            Icon(Icons.Filled.ArrowUpward, contentDescription = "Move up",
                                modifier = Modifier.size(30.dp))
                        }
                    }
                    if (position < panelCount - 1) {
                        IconButton(onClick = { onMove(panel.id, position + 1) }) {
                            Icon(Icons.Filled.ArrowDownward, contentDescription = "Move down",
                                modifier = Modifier.size(30.dp))
                        }
                    }
                    IconButton(onClick = { onClose(panel.id) }) {
                        Icon(Icons.Filled.Close, contentDescription = "Close panel",
                            modifier = Modifier.size(30.dp))
                    }
                }
            }
            if (panel.loading) LinearProgressIndicator(Modifier.fillMaxWidth())
            panel.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            content()
        }
    }
}
