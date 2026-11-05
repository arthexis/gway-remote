package com.arthexis.gwayremote

import androidx.compose.runtime.Composable

/** Navigation for local panels, deliberately separate from backend execution policies. */
data class LocalPanelState(val openIds: List<String> = emptyList()) {
    init {
        require(openIds.distinct().size == openIds.size)
        require(openIds.all { isPanel(it) })
    }

    fun toggle(id: String): LocalPanelState =
        if (id in openIds) close(id) else open(id)

    fun open(id: String): LocalPanelState {
        require(isPanel(id)) { "Unknown local panel: $id" }
        return if (id in openIds) this else copy(openIds = listOf(id) + openIds)
    }

    fun close(id: String): LocalPanelState = copy(openIds = openIds - id)

    fun move(id: String, index: Int): LocalPanelState {
        val position = openIds.indexOf(id)
        if (position < 0) return this
        val next = openIds.toMutableList()
        next.removeAt(position)
        next.add(index.coerceIn(0, next.size), id)
        return copy(openIds = next)
    }

    companion object {
        fun isPanel(id: String): Boolean =
            FeatureRegistry.get(id)?.kind == FeatureKind.LOCAL_PANEL && id != "app-update"
    }
}

@Composable
internal fun LocalPanelHost(
    state: LocalPanelState,
    endpoint: String,
    token: String,
    onClose: (String) -> Unit,
    onMove: (String, Int) -> Unit
) {
    state.openIds.forEachIndexed { index, id ->
        val title = FeatureRegistry.get(id)?.label ?: return@forEachIndexed
        PanelChrome(id, title, index, state.openIds.size, onMove, onClose) {
            when (id) {
                "deployments" -> DeploymentsPanel(endpoint, token)
                "mcp-access" -> McpAccessPanel(onClose = { onClose(id) })
                "github-health" -> GitHubHealthPanel(endpoint, token)
            }
        }
    }
}
