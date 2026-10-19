package com.arthexis.gwayremote

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/** Independent read-only diagnostics in one System card. */
@Composable
internal fun SystemUnifiedPanel(
    api: OperationViewModel.SystemCheck,
    status: OperationViewModel.SystemCheck,
    refresh: (String?) -> Unit
) {
    var selected by remember { mutableStateOf("status") }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(onClick = { selected = "status" }) { Text("Status") }
        OutlinedButton(onClick = { selected = "api-health" }) { Text("API Health") }
    }
    val check = if (selected == "status") status else api
    val title = if (selected == "status") "System status" else "API health"
    Text(title, style = MaterialTheme.typography.titleSmall)
    if (check.loading) LinearProgressIndicator(Modifier.fillMaxWidth())
    check.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
    check.output?.let { GenericResultRenderer(it) }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(onClick = { refresh(selected) }) { Text("Refresh $title") }
        OutlinedButton(onClick = { refresh(null) }) { Text("Refresh both") }
    }
}
