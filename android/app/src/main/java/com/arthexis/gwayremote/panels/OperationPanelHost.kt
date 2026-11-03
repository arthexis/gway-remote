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
    csmsView: String?,
    onSelectCsmsView: (String) -> Unit,
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
    agentAssignments: List<JSONObject>,
    agentInstance: String,
    agentAssignmentsLoading: Boolean,
    agentAssignmentsError: String,
    onRefreshAgentAssignments: () -> Unit,
    onAgentAssignmentsError: (String) -> Unit,
    agentAssignmentsExpanded: Boolean,
    onAgentAssignmentsExpanded: (Boolean) -> Unit,
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
                    CsmsUnifiedPanel(panel, onRefresh, onCsmsInspect, csmsView, onSelectCsmsView)
                } else PanelContent(
                    panel = panel,
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
                        localAgent = agentInstance,
                        loading = agentAssignmentsLoading,
                        error = agentAssignmentsError,
                        onRefresh = onRefreshAgentAssignments,
                        onError = onAgentAssignmentsError,
                        expanded = agentAssignmentsExpanded,
                        onExpandedChange = onAgentAssignmentsExpanded
                    )
                }
                if (panel.id != "notifications" && panel.id != "system" && panel.id != "csms") PanelActions(spec = spec, panel = panel, onRefresh = onRefresh, onInput = onInput, onExecute = onExecute, motifs = motifs)
                if (spec.policy == ExecutionPolicy.AUTO_READ || panel.id == "csms-view" || panel.id == "lcd" || panel.id == "sound") {
                    // Common read actions are rendered by PanelActions.
                } else if (panel.id == "benchmark") {
                    benchmarkContent()
                } else {
                    Text("Controls remain available in the existing interface until UI-4.",
                        style = MaterialTheme.typography.bodySmall)
                }
        }
    }

}
