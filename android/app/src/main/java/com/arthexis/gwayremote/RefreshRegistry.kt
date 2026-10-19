package com.arthexis.gwayremote

/** Only declaratively supported, read-only requests may be invoked by pull-to-refresh. */
enum class RefreshKind { SYSTEM, CSMS, STANDARD, SIMULATOR, AGENT_OPS }

data class RefreshTarget(val panelId: String, val kind: RefreshKind)

/** Pure planning, independent of Compose and network. */
object RefreshRegistry {
    private val supported = mapOf(
        "system" to RefreshKind.SYSTEM,
        "csms" to RefreshKind.CSMS,
        "tasks" to RefreshKind.STANDARD,
        "agent-ops" to RefreshKind.AGENT_OPS,
        "simulator" to RefreshKind.SIMULATOR
    )

    fun targets(state: OperationPanelState): List<RefreshTarget> =
        state.panels.mapNotNull { panel ->
            supported[panel.id]?.let { RefreshTarget(panel.id, it) }
        }
}
