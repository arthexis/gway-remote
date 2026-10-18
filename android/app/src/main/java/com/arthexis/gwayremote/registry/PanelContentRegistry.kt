package com.arthexis.gwayremote

/**
 * Maps stable operation IDs to specialized result presentations.
 * Input controls and execution policies remain separate from result rendering.
 */
enum class PanelContentKind {
    GENERIC, AGENT_OPS, TASK_HISTORY, TASK_DETAIL,
    SIMULATOR_RESULTS, SIMULATOR_STATUS, CSMS_HEALTH, CSMS_INSPECTION
}

object PanelContentRegistry {
    private val specialized = mapOf(
        "agent-ops" to PanelContentKind.AGENT_OPS,
        "tasks" to PanelContentKind.TASK_HISTORY,
        "task-detail" to PanelContentKind.TASK_DETAIL,
        "simulator-results" to PanelContentKind.SIMULATOR_RESULTS,
        "simulator-status" to PanelContentKind.SIMULATOR_STATUS,
        "csms" to PanelContentKind.CSMS_HEALTH,
        "csms-view" to PanelContentKind.CSMS_INSPECTION
    )

    init {
        require(specialized.keys.all { OperationRegistry.get(it) != null }) {
            "Panel content registered for unknown operation"
        }
    }

    fun kind(operationId: String): PanelContentKind =
        specialized[operationId] ?: PanelContentKind.GENERIC
}
