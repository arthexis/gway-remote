package com.arthexis.gwayremote

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.unit.dp
import org.json.JSONObject

/**
 * Common host for registered operation panels.
 * Keeps panel position, close/reorder actions and specialized controls separate
 * from the palette's feature searching and button layout.
 */
@Composable
internal fun OperationPanelHost(
    state: OperationPanelState,
    onClose: (String) -> Unit,
    onMove: (String, Int) -> Unit,
    onRefresh: (String) -> Unit,
    onCsmsInspect: (String) -> Unit,
    apiHealth: OperationViewModel.SystemCheck,
    systemStatus: OperationViewModel.SystemCheck,
    onRefreshSystem: (String?) -> Unit,
    onInput: (String, String, String) -> Unit,
    onExecute: (String, Map<String, String>) -> Unit,
    motifs: List<String>,
    lcdNotification: OperationViewModel.NotificationRun,
    soundNotification: OperationViewModel.NotificationRun,
    onNotificationInput: (String, String, String) -> Unit,
    onExecuteNotification: (String, Map<String, String>) -> Unit,
    benchmarkContent: @Composable () -> Unit,
    simulatorStatus: String,
    onSimulatorCommand: (String, JSONObject) -> Unit,
    onSimulatorRead: (String, JSONObject) -> Unit,
    onSelectSimulatorPeer: (String, String) -> Unit,
    onInspectTask: (String) -> Unit,
    taskDetail: String?,
    taskDetailLoading: Boolean,
    taskDetailError: String?,
    taskDetailSelection: String?,
    agentAssignments: List<JSONObject>,
    agentAssignmentsLoading: Boolean,
    agentAssignmentsError: String,
    onRefreshAgentAssignments: () -> Unit,
    onAgentAssignmentsError: (String) -> Unit,
    agentSendLoading: Boolean,
    agentSendResult: String?,
    agentSendError: String?,
    onAgentSend: (String, String) -> Unit,
    onAgentCopyPrompt: (String) -> Unit,
    agentObserveLoading: Boolean,
    agentObserveResult: String?,
    agentObserveError: String?,
    onAgentObserve: (String, String) -> Unit
) {
    state.panels.forEachIndexed { position, panel ->
        val spec = OperationRegistry.get(panel.id) ?: return@forEachIndexed
        StandardPanel(
            spec = spec,
            panel = panel,
            position = position,
            panelCount = state.panels.size,
            onMove = onMove,
            onClose = onClose
        ) {
                if (panel.id == "notifications") {
                    NotificationsUnifiedPanel(lcdNotification, soundNotification, motifs,
                        onNotificationInput, onExecuteNotification)
                } else if (panel.id == "system") {
                    SystemUnifiedPanel(apiHealth, systemStatus, onRefreshSystem)
                } else if (panel.id == "csms") {
                    CsmsUnifiedPanel(panel, onRefresh, onCsmsInspect)
                } else if (panel.id == "tasks") {
                    TasksUnifiedPanel(panel, taskDetail, taskDetailLoading, taskDetailError, taskDetailSelection, onInspectTask)
                } else PanelContent(
                    panel = panel,
                    onInspectTask = onInspectTask,
                    agentSendLoading = agentSendLoading,
                    agentSendResult = agentSendResult,
                    agentSendError = agentSendError,
                    onAgentSend = onAgentSend,
                    onAgentCopyPrompt = onAgentCopyPrompt,
                    agentObserveLoading = agentObserveLoading,
                    agentObserveResult = agentObserveResult,
                    agentObserveError = agentObserveError,
                    onAgentObserve = onAgentObserve
                )
                if (panel.id == "agent-ops") {
                    AgentAssignmentsSection(
                        issues = agentAssignments,
                        loading = agentAssignmentsLoading,
                        error = agentAssignmentsError,
                        onRefresh = onRefreshAgentAssignments,
                        onError = onAgentAssignmentsError
                    )
                }
                if (panel.id != "notifications" && panel.id != "system" && panel.id != "csms" && panel.id != "tasks") PanelActions(spec = spec, panel = panel, onRefresh = onRefresh, onInput = onInput, onExecute = onExecute, motifs = motifs)
                if (panel.id == "simulator") {
                    SimulatorUnifiedPanel(
                        panel = panel,
                        status = simulatorStatus,
                        onInput = onInput,
                        onRead = onSimulatorRead,
                        onCommand = onSimulatorCommand
                    )
                }
                if (spec.policy == ExecutionPolicy.AUTO_READ || panel.id == "task-detail" || panel.id == "csms-view" || panel.id == "lcd" || panel.id == "sound" || panel.id == "simulator") {
                    // Common read and task-detail actions are rendered by PanelActions.
                } else if (panel.id == "simulator-discover") {
                    val discovered = remember(panel.output) {
                        runCatching {
                            val peers = JSONObject(panel.output ?: "{}").optJSONObject("result")
                                ?.optJSONArray("peers")
                            if (peers == null) emptyList<String>()
                            else (0 until peers.length()).mapNotNull { index ->
                                peers.optJSONObject(index)?.optString("host")
                                    ?.takeIf { it.isNotBlank() }
                            }.distinct()
                        }.getOrDefault(emptyList())
                    }
                    if (discovered.isNotEmpty()) {
                        Text("Discovered Ethernet peers: ${discovered.size}")
                        discovered.forEach { peer ->
                            OutlinedButton(onClick = {
                                onSelectSimulatorPeer(peer, panel.inputs["port"] ?: "9000")
                            }) { Text("Use $peer for Start") }
                        }
                    }

                    val host = panel.inputs["host"].orEmpty()
                    val port = panel.inputs["port"] ?: "9000"
                    OutlinedTextField(host, { onInput(panel.id, "host", it) },
                        label = { Text("Ethernet target (optional)") }, singleLine = true)
                    OutlinedTextField(port, { onInput(panel.id, "port", it) },
                        label = { Text("CSMS port") }, singleLine = true)
                    Button(
                        enabled = !panel.loading && port.toIntOrNull()?.let { it in 1..65535 } == true,
                        onClick = { onExecute(panel.id, mapOf("host" to host, "port" to port)) }
                    ) { Text("Discover / check target") }
                } else if (panel.id == "benchmark") {
                    benchmarkContent()
                } else if (panel.id == "simulator-start" || panel.id == "simulator-stop") {
                    val host = panel.inputs["host"].orEmpty()
                    val port = panel.inputs["port"] ?: "9000"
                    var pending by remember(panel.id) { mutableStateOf<Pair<String, JSONObject>?>(null) }
                    if (panel.id == "simulator-start") {
                        OutlinedTextField(host, { onInput(panel.id, "host", it) },
                            label = { Text("Ethernet target host") }, singleLine = true)
                        OutlinedTextField(port, { onInput(panel.id, "port", it) },
                            label = { Text("CSMS port") }, singleLine = true)
                        // Reuse the original validated scenarios and payload builder;
                        // avoid duplicating its charging parameter contract.
                        SimulatorControls(host, port, simulatorStatus, panel.loading) { command, args ->
                            pending = command to args
                        }
                    } else {
                        Text("Simulator: $simulatorStatus")
                        Button(enabled = !panel.loading && simulatorStatus.startsWith("running"),
                            onClick = { pending = "simulator-stop" to JSONObject() }) {
                            Text("Stop simulation")
                        }
                    }
                    pending?.let { (command, args) ->
                        ConfirmPanelAction(
                            title = "Confirm simulator operation",
                            description = "Execute $command on the configured simulator?",
                            onConfirm = {
                                pending = null
                                onSimulatorCommand(command, args)
                            },
                            onCancel = { pending = null }
                        )
                    }
                } else {
                    Text("Controls remain available in the existing interface until UI-4.",
                        style = MaterialTheme.typography.bodySmall)
                }
        }
    }

}
