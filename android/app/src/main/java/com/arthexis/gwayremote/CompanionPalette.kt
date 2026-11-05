package com.arthexis.gwayremote

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext

/** Palette wiring is kept outside the activity; controllers retain execution authority. */
@Composable
internal fun CompanionPalette(
    operationModel: OperationViewModel,
    agentModel: AgentOpsViewModel,
    agentAssignmentsExpanded: Boolean,
    onAgentAssignmentsExpanded: (Boolean) -> Unit,
    benchmarkContent: @Composable () -> Unit,
    motifs: List<String>,
    quotationsOpen: Boolean,
    onToggleQuotations: () -> Unit,
    localPanels: LocalPanelState,
    onToggleLocalPanel: (String) -> Unit,
    updating: Boolean,
    hasUpdate: Boolean,
    onUpdate: () -> Unit
) {
    val agentUiContext = LocalContext.current
    OperationPalette(
            state = operationModel.panels,
            onOpen = operationModel::open,
            onClose = operationModel::close,
            onMove = operationModel::move,
            onRefresh = operationModel::refresh,
            onCsmsInspect = operationModel::inspectCsms,
            csmsView = operationModel.csmsView,
            onSelectCsmsView = operationModel::selectCsmsView,
            apiHealth = operationModel.apiHealth,
            systemStatus = operationModel.systemStatus,
            onRefreshSystem = operationModel::refreshSystem,
            agentAssignments = agentModel.issues,
            agentInstance = agentModel.localAgent,
            agentAssignmentsLoading = agentModel.issuesLoading,
            agentAssignmentsError = agentModel.issuesError,
            onRefreshAgentAssignments = agentModel::refreshAssignments,
            onAgentAssignmentsError = agentModel::reportAssignmentsError,
            agentAssignmentsExpanded = agentAssignmentsExpanded,
            onAgentAssignmentsExpanded = { agentAssignmentsExpanded = it },
            agentSendLoading = agentModel.sendLoading,
            agentSendResult = agentModel.sendResult,
            agentSendError = agentModel.sendError,
            agentObserveLoading = agentModel.observeLoading,
            agentObserveResult = agentModel.observeResult,
            agentObserveError = agentModel.observeError,
            onAgentObserve = agentModel::observe,
            onAgentCopyPrompt = { ref ->
                agentModel.preview(ref) { prompt ->
                    val clipboard = agentUiContext.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                    clipboard.setPrimaryClip(ClipData.newPlainText("Agent issue prompt", prompt))
                }
            },
            onAgentSend = agentModel::send,
            benchmarkContent = benchmarkContent,
            motifs = motifs,
            lcdNotification = operationModel.lcdNotification,
            soundNotification = operationModel.soundNotification,
            onNotificationInput = operationModel::notificationInput,
            onExecuteNotification = operationModel::executeNotification,
            onInput = operationModel::input,
            onExecute = operationModel::execute,
            extraActions = homeActions(
                quotationsOpen = quotationsOpen,
                onToggleQuotations = onToggleQuotations,
                localPanels = localPanels,
                onToggleLocalPanel = onToggleLocalPanel,
                updating = updating,
                hasUpdate = hasUpdate,
                onUpdate = onUpdate
            )
        )
}

private fun homeActions(
    quotationsOpen: Boolean,
    onToggleQuotations: () -> Unit,
    localPanels: LocalPanelState,
    onToggleLocalPanel: (String) -> Unit,
    updating: Boolean,
    hasUpdate: Boolean,
    onUpdate: () -> Unit
): List<PaletteAction> {
    return listOf(
                PaletteAction(
                    id = "odoo-quotations",
                    label = if (quotationsOpen) "Ocultar Cotizaciones" else "Cotizaciones",
                    icon = "file-text",
                    onClick = onToggleQuotations
                ),
                PaletteAction(
                    id = "deployments",
                    label = "Deployments",
                    icon = "rocket",
                    onClick = { onToggleLocalPanel("deployments") }
                ),
                PaletteAction(
                    id = "mcp-access",
                    label = "MCP Access",
                    icon = "key-round",
                    onClick = { onToggleLocalPanel("mcp-access") }
                ),
                PaletteAction(
                    id = "github-health",
                    label = "GitHub Health",
                    icon = "github",
                    onClick = { onToggleLocalPanel("github-health") }
                ),
                PaletteAction(
                    id = "app-update",
                    label = if (updating) "Updating…" else "App update",
                    icon = "update",
                    onClick = onUpdate,
                    enabled = !updating,
                    attention = hasUpdate
                )
        )
}
