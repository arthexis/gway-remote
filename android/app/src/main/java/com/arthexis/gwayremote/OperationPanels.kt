package com.arthexis.gwayremote

/**
 * UI-2: pure immutable state for independently open operation panels.
 * No network, Android lifecycle or execution side effects live in this manager.
 */
data class OperationPanel(
    val id: String,
    val inputs: Map<String, String> = emptyMap(),
    val loading: Boolean = false,
    val output: String? = null,
    val error: String? = null,
    val revision: Long = 0L
)

data class OpenPanelResult(
    val state: OperationPanelState,
    val shouldAutoRun: Boolean
)

data class OperationPanelState(
    val panels: List<OperationPanel> = emptyList(),
    val nextRevision: Long = 1L
) {
    init {
        require(panels.map { it.id }.distinct().size == panels.size) { "duplicate open panels" }
        require(panels.all { OperationRegistry.get(it.id) != null }) { "unknown operation" }
    }

    fun open(id: String): OpenPanelResult {
        val spec = requireNotNull(OperationRegistry.get(id)) { "unknown operation: $id" }
        if (panels.any { it.id == id }) return OpenPanelResult(this, false)
        return OpenPanelResult(copy(panels = listOf(OperationPanel(id)) + panels), spec.autoExecuteOnOpen)
    }

    fun close(id: String): OperationPanelState =
        copy(panels = panels.filterNot { it.id == id })

    fun move(id: String, index: Int): OperationPanelState {
        val position = panels.indexOfFirst { it.id == id }
        if (position < 0) return this
        val next = panels.toMutableList()
        val selected = next.removeAt(position)
        next.add(index.coerceIn(0, next.size), selected)
        return copy(panels = next)
    }

    fun input(id: String, key: String, value: String): OperationPanelState {
        require(key.isNotBlank()) { "input key cannot be blank" }
        return edit(id) { it.copy(inputs = it.inputs + (key to value)) }
    }

    /** Start is called only by the controller after policy validation. */
    fun start(id: String): OperationPanelState {
        if (panels.none { it.id == id }) return this
        val token = nextRevision
        return edit(id) { it.copy(loading = true, output = null, error = null, revision = token) }
            .copy(nextRevision = token + 1)
    }

    /** Ignore stale responses, including those for a closed/reopened panel. */
    fun complete(id: String, revision: Long, output: String): OperationPanelState =
        edit(id) { if (it.loading && it.revision == revision) it.copy(loading = false, output = output) else it }

    fun fail(id: String, revision: Long, message: String): OperationPanelState =
        edit(id) { if (it.loading && it.revision == revision) it.copy(loading = false, error = message) else it }

    /** Restored panels never trigger auto-run; loading jobs cannot be resurrected. */
    fun restore(ids: List<String>): OperationPanelState {
        val unique = ids.distinct().filter { OperationRegistry.get(it) != null }
        return copy(panels = unique.map(::OperationPanel))
    }

    fun unopened(query: String = ""): List<OperationSpec> {
        val opened = panels.map { it.id }.toSet()
        return OperationRegistry.search(query).filterNot { it.id in opened }
    }

    private inline fun edit(id: String, transform: (OperationPanel) -> OperationPanel): OperationPanelState =
        copy(panels = panels.map { if (it.id == id) transform(it) else it })
}

/** Controller boundary: confirmation and input validation are not delegated to the panel UI. */
object PanelExecution {
    fun canRun(id: String, explicit: Boolean, confirmed: Boolean, inputsValid: Boolean): Boolean {
        val spec = OperationRegistry.get(id) ?: return false
        if (!inputsValid) return false
        return when (spec.policy) {
            ExecutionPolicy.AUTO_READ -> true
            ExecutionPolicy.EXPLICIT_INPUT -> explicit
            ExecutionPolicy.CONFIRM -> explicit && confirmed
        }
    }
}
