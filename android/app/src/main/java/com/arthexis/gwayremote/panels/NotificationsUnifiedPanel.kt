package com.arthexis.gwayremote

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/** Reuses the existing LCD/Sound controls and validation inside one card. */
@Composable
internal fun NotificationsUnifiedPanel(
    lcd: OperationViewModel.NotificationRun,
    sound: OperationViewModel.NotificationRun,
    motifs: List<String>,
    onInput: (String, String, String) -> Unit,
    onExecute: (String, Map<String, String>) -> Unit
) {
    var selected by remember { mutableStateOf("sound") }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(onClick = { selected = "sound" }) { Text("Sound") }
        OutlinedButton(onClick = { selected = "lcd" }) { Text("LCD message") }
    }
    val state = if (selected == "sound") sound else lcd
    val spec = requireNotNull(OperationRegistry.get(selected))
    PanelActions(spec, OperationPanel(selected, state.inputs, state.loading, state.output, state.error),
        onRefresh = {}, onInput = onInput, onExecute = onExecute, motifs = motifs)
    if (state.loading) LinearProgressIndicator(Modifier.fillMaxWidth())
    state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
    state.output?.let { GenericResultRenderer(it) }
}
