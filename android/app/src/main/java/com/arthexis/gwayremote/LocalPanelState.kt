package com.arthexis.gwayremote

/** Legacy local panel state maintained for regression contract; no runtime host uses it. */
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

