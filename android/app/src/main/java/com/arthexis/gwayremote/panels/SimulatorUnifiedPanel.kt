package com.arthexis.gwayremote

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import org.json.JSONObject

/** One panel for simulator inspection, discovery, start, stop, and results. */
@Composable
internal fun SimulatorUnifiedPanel(
    panel: OperationPanel,
    status: String,
    onInput: (String, String, String) -> Unit,
    onRead: (String, JSONObject) -> Unit,
    onCommand: (String, JSONObject) -> Unit,
    onSelectRead: (String) -> Unit = {}
) {
    var selected by remember(panel.id) { mutableStateOf("Status") }
    var pending by remember(panel.id) { mutableStateOf<Pair<String, JSONObject>?>(null) }
    val tabs = listOf("Status", "Discover", "Start / Stop", "Results")
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Simulator: $status", style = MaterialTheme.typography.bodyMedium)
        // Wrapping keeps the controls usable at phone widths.
        tabs.chunked(2).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                row.forEach { name ->
                    OutlinedButton(
                        modifier = Modifier.weight(1f),
                        onClick = {
                            selected = name
                            if (name == "Status") onSelectRead("simulator-status")
                            else if (name == "Results") onSelectRead("simulator-results")
                        }
                    ) { Text(name, maxLines = 2) }
                }
            }
        }
        when (selected) {
            "Status" -> Text("Pull down to refresh simulator status", style = MaterialTheme.typography.bodySmall)
            "Results" -> Text("Pull down to reload simulator results", style = MaterialTheme.typography.bodySmall)
            "Discover" -> {
                val host = panel.inputs["host"].orEmpty()
                val port = panel.inputs["port"] ?: "9000"
                OutlinedTextField(host, { onInput(panel.id, "host", it) },
                    modifier = Modifier.fillMaxWidth(), label = { Text("Ethernet target (optional)") })
                OutlinedTextField(port, { onInput(panel.id, "port", it) },
                    modifier = Modifier.fillMaxWidth(), label = { Text("CSMS port") })
                Button(
                    enabled = !panel.loading && port.toIntOrNull()?.let { it in 1..65535 } == true,
                    onClick = {
                        val args = JSONObject().put("port", port.toInt())
                        if (host.isNotBlank()) args.put("host", host.trim())
                        onRead("simulator-discover", args)
                    }
                ) { Text("Discover peers") }
                val peers = remember(panel.output) {
                    runCatching {
                        val arr = JSONObject(panel.output ?: "{}").optJSONObject("result")?.optJSONArray("peers")
                        if (arr == null) emptyList() else (0 until arr.length()).mapNotNull { n ->
                            arr.optJSONObject(n)?.optString("host")?.takeIf(String::isNotBlank)
                        }.distinct()
                    }.getOrDefault(emptyList())
                }
                peers.forEach { peer ->
                    OutlinedButton(onClick = { onInput(panel.id, "host", peer); selected = "Start / Stop" }) {
                        Text("Use $peer")
                    }
                }
            }
            "Start / Stop" -> {
                val host = panel.inputs["host"].orEmpty()
                val port = panel.inputs["port"] ?: "9000"
                OutlinedTextField(host, { onInput(panel.id, "host", it) },
                    modifier = Modifier.fillMaxWidth(), label = { Text("Ethernet target host") })
                OutlinedTextField(port, { onInput(panel.id, "port", it) },
                    modifier = Modifier.fillMaxWidth(), label = { Text("CSMS port") })
                SimulatorControls(host, port, status, panel.loading) { command, args ->
                    pending = command to args
                }
            }
        }
        // Present the most recent command response in the same card.
        panel.output?.let { output ->
            Text("Latest response", style = MaterialTheme.typography.titleSmall)
            if (selected == "Results") SimulatorResultsPanel(output)
            else if (selected == "Status") SimulatorStatusPanel(output)
            else Text(output, style = MaterialTheme.typography.bodySmall)
        }
        pending?.let { (command, args) ->
            ConfirmPanelAction(
                title = "Confirm simulator operation",
                description = "Execute $command on the configured simulator?",
                onConfirm = { pending = null; onCommand(command, args) },
                onCancel = { pending = null }
            )
        }
    }
}
