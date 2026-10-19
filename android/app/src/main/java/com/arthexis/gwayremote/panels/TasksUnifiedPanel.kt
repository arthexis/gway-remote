package com.arthexis.gwayremote

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/** Task history stays visible while the selected task is inspected below it. */
@Composable
internal fun TasksUnifiedPanel(
    panel: OperationPanel,
    detail: String?,
    detailLoading: Boolean,
    detailError: String?,
    selection: String?,
    inspect: (String) -> Unit
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        TaskHistoryPanel(panel.output, inspect)
        if (selection != null) {
            HorizontalDivider()
            Text("Selected task: ${selection.take(8)}", style = MaterialTheme.typography.titleSmall)
            if (detailLoading) LinearProgressIndicator(Modifier.fillMaxWidth())
            detailError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            TaskDetailPanel(detail)
        }
    }
}
