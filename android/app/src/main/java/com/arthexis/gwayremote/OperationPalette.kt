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
    onRefresh: (String) -> Unit
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
