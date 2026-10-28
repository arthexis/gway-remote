package com.arthexis.gwayremote

import androidx.compose.runtime.Composable

/** Dispatches result presentation independently of panel layout and actions. */
@Composable
internal fun PanelContent(
    panel: OperationPanel,
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
    when (PanelContentRegistry.kind(panel.id)) {
        PanelContentKind.AGENT_OPS ->
            AgentOpsPanel(panel.output, agentSendLoading, agentSendResult, agentSendError,
                onAgentSend, onAgentCopyPrompt, agentObserveLoading, agentObserveResult,
                agentObserveError, onAgentObserve)
        PanelContentKind.SIMULATOR_RESULTS -> SimulatorResultsPanel(panel.output)
        PanelContentKind.SIMULATOR_STATUS -> SimulatorStatusPanel(panel.output)
        PanelContentKind.CSMS_HEALTH -> CsmsHealthPanel(panel.output)
        PanelContentKind.CSMS_INSPECTION -> CsmsInspectionPanel(panel.output)
        PanelContentKind.GENERIC -> panel.output?.let { GenericResultRenderer(it) }
    }
}
