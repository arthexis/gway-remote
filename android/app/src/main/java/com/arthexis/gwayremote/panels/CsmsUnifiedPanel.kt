package com.arthexis.gwayremote

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import org.json.JSONObject

/** Health and read-only CSMS inspection share one operation card. */
@Composable
internal fun CsmsUnifiedPanel(
    panel: OperationPanel,
    onRefresh: (String) -> Unit,
    onInspect: (String) -> Unit,
    selectedView: String?,
    onSelectView: (String) -> Unit
) {
    val views = listOf("status", "chargers", "charge-points", "transactions",
        "events", "alerts", "rfid-report", "report")
    val visibleView = selectedView ?: "status"
    var menuOpen by remember(panel.id) { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Box {
                OutlinedButton(onClick = { menuOpen = true }) {
                    Text("Inspect: $visibleView ▾", maxLines = 2)
                }
                DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                    views.forEach { view ->
                        DropdownMenuItem(text = { Text(view) }, onClick = {
                            onSelectView(view)
                            menuOpen = false
                        })
                    }
                }
            }
        }
        Button(enabled = !panel.loading, onClick = { onInspect(visibleView) }) {
            Text("Inspect $visibleView")
        }
        panel.output?.let { output ->
            val response = remember(output) {
                runCatching { JSONObject(output) }.getOrNull()
            }
            if (response?.optString("command") == "csms-view") {
                CsmsInspectionPanel(output, visibleView)
            } else {
                CsmsHealthPanel(output)
            }
        }
    }
}
